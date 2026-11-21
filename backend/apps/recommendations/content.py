"""
Content-based filtering — "photographers similar to the ones you liked".

HOW IT WORKS
------------
1. Every photographer is described as a text document built from what they
   actually offer: categories, specializations, city, price band, tagline,
   bio, portfolio album titles/descriptions, portfolio image captions and
   visual styles, and their active services.
2. A TF-IDF vectoriser (fitted offline by ml/pipelines/train_content.py and
   saved as content.joblib) turns each document into a vector.
3. A buyer's TASTE PROFILE is the weighted average of the vectors of the
   photographers they viewed, saved, messaged or booked. Stronger signals
   count more (INTERACTION_WEIGHTS: a booking outweighs a view).
4. Content score = cosine similarity between the buyer's taste profile and
   each candidate photographer.

Unlike collaborative filtering, this needs no other buyers: a single
interaction is enough to find photographers with a similar style, which is
exactly the cold-start case CF cannot handle.

The document builder lives HERE and is imported by the training pipeline, so
training and serving can never describe a photographer differently.

Like the rest of the engine, nothing in this module raises: every failure
returns zeros and the blend redistributes the weight.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("snapsphere")

ARTIFACT_NAME = "content.joblib"

#: Price bands (PKR) turned into tokens so budget level is part of "style".
PRICE_BANDS = (
    (25_000, "price_budget"),
    (50_000, "price_mid"),
    (100_000, "price_upper_mid"),
    (200_000, "price_premium"),
)
PRICE_TOP_BAND = "price_luxury"

#: Interaction types that say nothing about taste are left out of the profile.
_IGNORED_INTERACTIONS = {"SEARCH"}

_model = None
_model_loaded = False


# ═══════════════════════════════════════════════════════════════════════════
# PHOTOGRAPHER DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════
def _token(prefix: str, value: str) -> str:
    """'Bright & Airy' → 'style_bright_airy' — one token, never split by TF-IDF."""
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return f"{prefix}_{slug}" if slug else ""


def price_band(base_price) -> str:
    price = float(base_price or 0)
    if price <= 0:
        return ""
    for upper, label in PRICE_BANDS:
        if price < upper:
            return label
    return PRICE_TOP_BAND


def photographer_documents(photographers: list) -> dict[int, str]:
    """
    {photographer_id: document} for a batch of PhotographerProfile rows.

    Portfolio and service text is loaded in three queries for the whole batch,
    not per photographer. Categories and specializations use the prefetch the
    list selectors already apply.
    """
    from apps.catalog.models import Service
    from apps.portfolio.models import PortfolioAlbum, PortfolioImage

    ids = [p.pk for p in photographers if p.pk]
    if not ids:
        return {}

    extra: dict[int, list[str]] = defaultdict(list)

    for pid, title, description, category in PortfolioAlbum.objects.filter(
        photographer_id__in=ids, is_deleted=False
    ).values_list("photographer_id", "title", "description", "category__name"):
        extra[pid] += [title or "", description or "", _token("cat", category or "")]

    for pid, caption, style, shot, category in PortfolioImage.objects.filter(
        photographer_id__in=ids, is_deleted=False
    ).values_list("photographer_id", "caption", "visual_style", "shot_type", "category__name"):
        extra[pid] += [
            caption or "",
            _token("style", style or ""),
            _token("shot", shot or ""),
            _token("cat", category or ""),
        ]

    for pid, title, description, category in Service.objects.filter(
        photographer_id__in=ids, is_deleted=False, is_active=True
    ).values_list("photographer_id", "title", "description", "category__name"):
        extra[pid] += [title or "", description or "", _token("cat", category or "")]

    documents = {}
    for p in photographers:
        parts = [_token("cat", c.name) for c in p.categories.all()]
        parts += [_token("spec", s.name) for s in p.specializations.all()]
        parts += [
            _token("city", getattr(p.user, "city", "") or ""),
            price_band(p.base_price),
            p.tagline or "",
            p.bio or "",
        ]
        parts += extra.get(p.pk, [])
        documents[p.pk] = " ".join(part for part in parts if part)
    return documents


# ═══════════════════════════════════════════════════════════════════════════
# BUYER TASTE PROFILE
# ═══════════════════════════════════════════════════════════════════════════
def buyer_history(buyer_id: int | None) -> dict[int, float]:
    """{photographer_id: summed interaction weight} for one buyer."""
    if not buyer_id:
        return {}
    from apps.recommendations.models import INTERACTION_WEIGHTS, BuyerInteraction

    history: dict[int, float] = defaultdict(float)
    for pid, itype in BuyerInteraction.objects.filter(buyer_id=buyer_id).values_list(
        "photographer_id", "interaction_type"
    ):
        if itype in _IGNORED_INTERACTIONS:
            continue
        history[pid] += float(INTERACTION_WEIGHTS.get(itype, 1.0))
    return dict(history)


def taste_profile(vectorizer, history: dict[int, float], documents: dict[int, str]):
    """
    Weighted, L2-normalised average of the history photographers' vectors.

    Returns a 1×V sparse row, or None when no history photographer has a
    document.
    """
    import numpy as np
    from sklearn.preprocessing import normalize

    ids = [pid for pid in history if documents.get(pid)]
    if not ids:
        return None
    vectors = vectorizer.transform([documents[pid] for pid in ids])
    weights = np.array([history[pid] for pid in ids], dtype=np.float64).reshape(-1, 1)
    profile = np.asarray(vectors.T @ weights).reshape(1, -1)  # dense 1×V weighted sum
    if not profile.any():
        return None
    return normalize(profile)


# ═══════════════════════════════════════════════════════════════════════════
# SERVING
# ═══════════════════════════════════════════════════════════════════════════
def load_model():
    """The fitted content artifact ({'vectorizer': ...}), or None."""
    global _model, _model_loaded
    if _model_loaded:
        return _model
    _model_loaded = True

    path = Path(settings.ML_ARTIFACTS_DIR) / ARTIFACT_NAME
    if not path.exists():
        logger.warning(
            "Content model missing at %s — content-based scores disabled. "
            "Run: python -m ml.train --only content", path,
        )
        return None
    try:
        import joblib

        _model = joblib.load(path)
        logger.info(
            "Content model loaded (vocabulary %s terms)",
            len(_model["vectorizer"].vocabulary_),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load the content artifact: %s", exc)
        _model = None
    return _model


def reset_model_cache() -> None:
    global _model, _model_loaded
    _model, _model_loaded = None, False


def content_similarity_scores(buyer_id: int | None, candidates: list) -> list[float]:
    """
    Cosine similarity of each candidate to the buyer's taste profile.

    Scaled so the best match in this candidate set is 1.0 (as the CF score
    is), keeping the two personal signals on the same scale in the blend.
    Zeros when the buyer has no history or the model is unavailable.
    """
    zeros = [0.0] * len(candidates)
    if not buyer_id or not candidates:
        return zeros

    model = load_model()
    if model is None:
        return zeros

    try:
        from apps.profiles.models import PhotographerProfile

        history = buyer_history(buyer_id)
        if not history:
            return zeros

        vectorizer = model["vectorizer"]
        candidate_ids = {p.pk for p in candidates}
        history_rows = list(
            PhotographerProfile.objects.filter(pk__in=list(history))
            .exclude(pk__in=candidate_ids)
            .select_related("user")
            .prefetch_related("categories", "specializations")
        )
        documents = photographer_documents(list(candidates) + history_rows)

        profile = taste_profile(vectorizer, history, documents)
        if profile is None:
            return zeros

        matrix = vectorizer.transform([documents.get(p.pk, "") for p in candidates])
        raw = (matrix @ profile.T).ravel()  # rows are L2-normalised → cosine
        peak = float(raw.max()) if len(raw) else 0.0
        if peak <= 0:
            return zeros
        return [max(float(s), 0.0) / peak for s in raw]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Content-based scoring failed: %s", exc)
        return zeros
