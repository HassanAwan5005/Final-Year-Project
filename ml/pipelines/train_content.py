"""
Content-based filtering — TF-IDF photographer profiles.

Produces ml/artifacts/content.joblib, used by
backend/apps/recommendations/content.py to score "photographers similar to the
ones this buyer liked".

WHY THIS TRAINS FROM THE DATABASE, NOT THE CSVs
-----------------------------------------------
The other models train on ml/data/raw/*.csv. The CSVs carry no descriptive
text about a photographer — no bio, tagline, specializations, portfolio or
services — and those are exactly what content-based filtering compares. So
this pipeline reads the live photographer catalogue through Django and uses
the SAME document builder as the serving path
(apps.recommendations.content.photographer_documents), so a photographer is
described identically at training and at serving time.

WHAT IS LEARNED
---------------
A TfidfVectorizer over photographer documents: the vocabulary and the IDF
weights (rare, distinctive terms such as a niche style count more than words
every photographer uses). No interaction data is used to fit it, so the
evaluation below cannot leak the held-out answer.

EVALUATION
----------
Leave-one-out on BuyerInteraction, the same protocol as train_cf.py: for every
buyer with 2+ photographers in their history, hide the most recent one, build
the taste profile from the rest, rank every other photographer by cosine
similarity, and record where the hidden photographer lands. Reported against
a random baseline and a popularity baseline.
"""

from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"


def _setup_django() -> None:
    """Make the backend importable and configured (no-op if already set up)."""
    backend = ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def make_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,   # 30 portfolio captions saying "wedding" ≠ 30× the evidence
        min_df=1,
        max_df=0.9,          # a term on 90%+ of profiles says nothing distinctive
        max_features=8000,
    )


def train() -> dict:
    _setup_django()

    from apps.profiles.models import PhotographerProfile
    from apps.recommendations.content import ARTIFACT_NAME, photographer_documents
    from apps.recommendations.models import INTERACTION_WEIGHTS, BuyerInteraction

    print("\n" + "=" * 74)
    print("TRAINING: content-based filter  (TF-IDF photographer profiles)")
    print("=" * 74)
    started = time.perf_counter()

    photographers = list(
        PhotographerProfile.objects.filter(is_deleted=False)
        .select_related("user")
        .prefetch_related("categories", "specializations")
    )
    if not photographers:
        raise RuntimeError("no photographers in the database — run seed_data first")

    documents = photographer_documents(photographers)
    ids = [p.pk for p in photographers]
    corpus = [documents.get(pid, "") for pid in ids]
    index = {pid: i for i, pid in enumerate(ids)}

    vectorizer = make_vectorizer()
    matrix = vectorizer.fit_transform(corpus)  # rows L2-normalised by TF-IDF
    print(f"  photographers          {len(ids)}")
    print(f"  vocabulary             {len(vectorizer.vocabulary_):,} terms")
    print(f"  mean terms / profile   {matrix.getnnz(axis=1).mean():.1f}")

    # ─── Buyer histories (ordered, weighted) ─────────────────────────────────
    histories: dict[int, list[tuple[int, float]]] = defaultdict(list)
    popularity = np.zeros(len(ids))
    for buyer_id, pid, itype in (
        BuyerInteraction.objects.exclude(interaction_type="SEARCH")
        .order_by("created_at", "id")
        .values_list("buyer_id", "photographer_id", "interaction_type")
    ):
        if pid not in index:
            continue
        weight = float(INTERACTION_WEIGHTS.get(itype, 1.0))
        histories[buyer_id].append((pid, weight))
        popularity[index[pid]] += weight

    # ─── Leave-one-out evaluation ────────────────────────────────────────────
    hits10 = hits20 = pop_hits10 = trials = 0
    ranks = []
    for events in histories.values():
        distinct = list(dict.fromkeys(pid for pid, _ in events))
        if len(distinct) < 2:
            continue
        held_out = distinct[-1]  # most recently engaged photographer
        rest: dict[int, float] = defaultdict(float)
        for pid, weight in events:
            if pid != held_out:
                rest[pid] += weight

        rows = [index[pid] for pid in rest]
        weights = np.array([rest[pid] for pid in rest]).reshape(-1, 1)
        profile = np.asarray(matrix[rows].T @ weights).reshape(1, -1)
        if not profile.any():
            continue
        profile = normalize(profile)

        scores = np.asarray(matrix @ profile.T).ravel()
        scores[rows] = -np.inf  # never re-recommend what the profile is built from
        rank = int((scores > scores[index[held_out]]).sum()) + 1
        ranks.append(rank)
        hits10 += int(rank <= 10)
        hits20 += int(rank <= 20)

        pop = popularity.copy()
        pop[rows] = -np.inf
        pop_rank = int((pop > pop[index[held_out]]).sum()) + 1
        pop_hits10 += int(pop_rank <= 10)
        trials += 1

    hit10 = hits10 / trials if trials else 0.0
    hit20 = hits20 / trials if trials else 0.0
    pop_hit10 = pop_hits10 / trials if trials else 0.0
    mean_rank = float(np.mean(ranks)) if ranks else 0.0
    random_baseline = 10 / len(ids)

    print(f"\n  leave-one-out trials   {trials}")
    print(f"  HitRate@10             {hit10:.4f}")
    print(f"  HitRate@20             {hit20:.4f}")
    print(f"  mean rank of held-out  {mean_rank:.1f} of {len(ids)}")
    print(f"  random baseline@10     {random_baseline:.4f}")
    print(f"  popularity baseline@10 {pop_hit10:.4f}")
    if random_baseline:
        print(f"  lift over random       {hit10 / random_baseline:.2f}×")

    duration = time.perf_counter() - started
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / ARTIFACT_NAME
    joblib.dump({"vectorizer": vectorizer, "photographer_ids": ids}, path, compress=3)
    print(f"\n  saved                  {ARTIFACT_NAME} "
          f"({path.stat().st_size / 1024:.0f} KB, {duration:.1f}s)")

    return {
        "name": "content",
        "algorithm": "TF-IDF photographer profiles + cosine similarity to buyer taste profile",
        "artifact_path": str(path),
        "training_rows": len(ids),
        "training_duration_seconds": round(duration, 2),
        "metrics": {
            "vocabulary_size": len(vectorizer.vocabulary_),
            "hit_rate_at_10": round(hit10, 4),
            "hit_rate_at_20": round(hit20, 4),
            "mean_rank_of_held_out": round(mean_rank, 1),
            "random_baseline": round(random_baseline, 4),
            "popularity_baseline_at_10": round(pop_hit10, 4),
            "lift": round(hit10 / random_baseline, 2) if random_baseline else 0,
            "trials": trials,
            "evaluation": "leave-one-out on BuyerInteraction, most recent photographer held out",
        },
    }


if __name__ == "__main__":
    train()
