"""
Photographer ranking model — a learned model, trained on observed outcomes.

Produces ml/artifacts/ranker.joblib (a SnapSphereRanker in "learned" mode).

WHAT IT LEARNS
--------------
"Given everything known about a photographer at time T — their reviews,
their engagement, their track record, their price and experience — how much
will buyers book them in the 180 days after T?"

    features  apps/recommendations/ranking_features.py, computed AS OF T
              (reviews, engagement, performance, price, experience, portfolio)
    target    percentile rank of bookings created in [T, T + 180 days)

The features only see history before T and the target only counts bookings
after T, so the answer cannot leak into the inputs. (The previous version
trained on buyer_interactions.csv, whose booking outcomes are random — there
was nothing to learn, and it shipped a hand-weighted formula instead.)

TRAINING DATA
-------------
Snapshots every SNAPSHOT_STEP_DAYS across the booking history in the
database, one row per photographer per snapshot. The most recent
TEST_SNAPSHOTS snapshots are held out as a TEMPORAL test set — the model is
evaluated on a future it never saw, which is how it is used in production.
Model selection uses GroupKFold cross-validation on the training snapshots,
grouped by photographer, so one photographer never sits on both sides of a
fold.

The selected model is finally refitted on every snapshot and shipped.
"""

from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_score

from ml.pipelines.features import FEATURE_ORDER, fit_scaler
from ml.pipelines.scorer import PRIOR_WEIGHTS, SnapSphereRanker, signal_test

ARTIFACT_DIR = Path(__file__).resolve().parents[1] / "artifacts"

TARGET_WINDOW_DAYS = 180
SNAPSHOT_STEP_DAYS = 60
HISTORY_BEFORE_FIRST_SNAPSHOT_DAYS = 120
TEST_SNAPSHOTS = 2

#: Feature groups, for reporting how much of the ranking each kind of signal drives.
FEATURE_GROUPS = {
    "reviews": [
        "bayesian_rating", "reviews_count_log", "sentiment_score",
        "recent_review_rating", "review_velocity_log",
    ],
    "engagement": [
        "engagement_rate", "views_90d_log", "clicks_90d_log", "portfolio_90d_log",
        "inquiries_90d_log", "wishlist_saves_log", "rec_click_rate", "conversion_rate_90d",
    ],
    "track_record": ["success_rate", "response_speed_score", "popularity_score", "recency_score"],
    "price_experience_portfolio": [
        "price_percentile", "years_experience", "portfolio_score_norm", "portfolio_image_count",
    ],
}


def _snapshot_dates(created: pd.Series) -> list:
    """Snapshot cut-offs spanning the dense part of the booking history."""
    created = created.sort_values()
    start = created.quantile(0.05) + timedelta(days=HISTORY_BEFORE_FIRST_SNAPSHOT_DAYS)
    end = created.quantile(0.98) - timedelta(days=TARGET_WINDOW_DAYS)
    dates, current = [], start.normalize()
    while current <= end:
        dates.append(current.to_pydatetime())
        current += timedelta(days=SNAPSHOT_STEP_DAYS)
    return dates


def build_dataset() -> pd.DataFrame:
    from ml.pipelines.train_content import _setup_django

    _setup_django()

    from django.db.models import Count

    from apps.bookings.constants import BookingStatus
    from apps.bookings.models import Booking
    from apps.profiles.models import PhotographerProfile
    from apps.recommendations.ranking_features import FEATURE_ORDER as SERVING_ORDER
    from apps.recommendations.ranking_features import build_feature_frame

    if list(SERVING_ORDER) != list(FEATURE_ORDER):
        raise RuntimeError("FEATURE_ORDER differs between ml/ and the backend — fix before training")

    photographers = list(PhotographerProfile.objects.filter(is_deleted=False).select_related("user"))
    if not photographers:
        raise RuntimeError("no photographers in the database — run seed_data first")

    valid = Booking.objects.exclude(
        status__in=[BookingStatus.CANCELLED, BookingStatus.REJECTED, BookingStatus.EXPIRED]
    )
    created = pd.Series(pd.to_datetime(list(valid.values_list("created_at", flat=True)), utc=True))
    snapshots = _snapshot_dates(created)
    if len(snapshots) <= TEST_SNAPSHOTS:
        raise RuntimeError(f"only {len(snapshots)} snapshots — not enough booking history")

    frames = []
    for i, as_of in enumerate(snapshots):
        X = build_feature_frame(photographers, as_of=as_of)
        future = dict(
            valid.filter(
                created_at__gte=as_of,
                created_at__lt=as_of + timedelta(days=TARGET_WINDOW_DAYS),
            )
            .values("photographer_id")
            .annotate(n=Count("id"))
            .values_list("photographer_id", "n")
        )
        X["future_bookings"] = [future.get(p.pk, 0) for p in photographers]
        X["target"] = X["future_bookings"].rank(pct=True)
        X["photographer_id"] = [p.pk for p in photographers]
        X["snapshot"] = i
        X["as_of"] = as_of.date()
        frames.append(X)
    return pd.concat(frames, ignore_index=True)


def _prior_scores(X: pd.DataFrame) -> np.ndarray:
    """The old hand-weighted formula, kept only as a comparison baseline."""
    return SnapSphereRanker(mode="prior", weights=PRIOR_WEIGHTS).predict(X)


def _importances(model, X_test, y_test, random_state) -> dict[str, float]:
    """Permutation importance on the temporal test set — model-agnostic."""
    from sklearn.inspection import permutation_importance

    result = permutation_importance(
        model, X_test, y_test, n_repeats=5, random_state=random_state,
        scoring="neg_root_mean_squared_error",
    )
    raw = np.clip(result.importances_mean, 0, None)
    total = raw.sum() or 1.0
    return {name: round(float(v / total), 4) for name, v in zip(FEATURE_ORDER, raw)}


def train(random_state: int = 42) -> dict:
    print("\n" + "=" * 74)
    print("TRAINING: photographer ranker  (learned, temporal)")
    print("=" * 74)
    started = time.perf_counter()

    data = build_dataset()
    n_snap = data["snapshot"].nunique()
    test_mask = data["snapshot"] >= n_snap - TEST_SNAPSHOTS
    train_df, test_df = data[~test_mask], data[test_mask]

    X_train, y_train = train_df[FEATURE_ORDER].astype(float), train_df["target"]
    X_test, y_test = test_df[FEATURE_ORDER].astype(float), test_df["target"]
    groups = train_df["photographer_id"]

    print(f"  snapshots              {n_snap}  ({data['as_of'].min()} → {data['as_of'].max()}, "
          f"every {SNAPSHOT_STEP_DAYS} days)")
    print(f"  rows                   {len(data)}  (train {len(train_df)}, "
          f"test {len(test_df)} = last {TEST_SNAPSHOTS} snapshots)")
    print(f"  features               {len(FEATURE_ORDER)}")
    print(f"  target                 percentile of bookings in the next {TARGET_WINDOW_DAYS} days")

    # ─── Diagnosis: which features carry signal (reported, not a gate) ───────
    diagnosis = signal_test(X_train, y_train)
    print("\n  ── signal test (training snapshots) ──")
    print(f"    {'feature':<24}{'pearson r':>12}{'p-value':>10}")
    for name, info in diagnosis["per_feature"].items():
        print(f"    {name:<24}{info['r']:>12.4f}{info['p']:>10.4f}   "
              f"{'SIGNAL' if info['signal'] else '-'}")

    # ─── Model selection by grouped CV on the training snapshots ─────────────
    scaler = fit_scaler(X_train)
    X_train_s, X_test_s = scaler.transform(X_train), scaler.transform(X_test)

    candidates = {
        "Ridge": Ridge(alpha=1.0),
        "RandomForest": RandomForestRegressor(
            n_estimators=300, max_depth=8, min_samples_leaf=5,
            random_state=random_state, n_jobs=-1,
        ),
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=300, learning_rate=0.05, max_depth=3,
            min_samples_leaf=10, subsample=0.9, random_state=random_state,
        ),
    }
    cv = GroupKFold(n_splits=5)
    baseline_rmse = float(np.sqrt(((y_test - y_train.mean()) ** 2).mean()))

    print(f"\n    {'model':<18}{'CV RMSE':>10}{'test RMSE':>12}{'test R²':>10}{'Spearman':>10}")
    results = {}
    for name, model in candidates.items():
        cv_rmse = -cross_val_score(
            model, X_train_s, y_train, cv=cv, groups=groups,
            scoring="neg_root_mean_squared_error",
        ).mean()
        model.fit(X_train_s, y_train)
        pred = np.clip(model.predict(X_test_s), 0, 1)
        results[name] = {
            "model": model,
            "cv_rmse": float(cv_rmse),
            "rmse": float(np.sqrt(mean_squared_error(y_test, pred))),
            "mae": float(mean_absolute_error(y_test, pred)),
            "r2": float(r2_score(y_test, pred)),
            "spearman": float(pd.Series(pred).corr(pd.Series(y_test.values), method="spearman")),
            "pred": pred,
        }
        r = results[name]
        print(f"    {name:<18}{r['cv_rmse']:>10.4f}{r['rmse']:>12.4f}{r['r2']:>10.4f}"
              f"{r['spearman']:>10.4f}")

    # Selected on CV only — the test set is never used to choose.
    best_name = min(results, key=lambda k: results[k]["cv_rmse"])
    best = results[best_name]

    # ─── Test-set evaluation ─────────────────────────────────────────────────
    k = max(len(test_df) // (TEST_SNAPSHOTS * 10), 1)  # top 10% of each snapshot
    precisions, prior_spearman = [], []
    test_eval = test_df.assign(pred=best["pred"], prior=_prior_scores(X_test))
    for _, snap in test_eval.groupby("snapshot"):
        true_top = set(snap.nlargest(k, "future_bookings").index)
        pred_top = set(snap.nlargest(k, "pred").index)
        precisions.append(len(true_top & pred_top) / k)
        prior_spearman.append(snap["prior"].corr(snap["target"], method="spearman"))
    precision_at_k = float(np.mean(precisions))
    prior_rho = float(np.mean(prior_spearman))
    beats_baseline = best["rmse"] < baseline_rmse

    importances = _importances(best["model"], X_test_s, y_test, random_state)
    group_share = {
        group: round(sum(importances[f] for f in feats), 4)
        for group, feats in FEATURE_GROUPS.items()
    }

    # ─── Ablation: engagement + reviews ON THEIR OWN ─────────────────────────
    # Permutation importance splits credit between correlated features (past
    # bookings, views and review velocity all move together), so it can show
    # a whole group near zero even when that group predicts well by itself.
    # Re-training the same algorithm on reviews + engagement only measures
    # what those signals achieve without the track-record features.
    subset = FEATURE_GROUPS["reviews"] + FEATURE_GROUPS["engagement"]
    sub_model = candidates[best_name].__class__(**candidates[best_name].get_params())
    sub_scaler = fit_scaler(X_train[subset])
    sub_model.fit(sub_scaler.transform(X_train[subset]), y_train)
    sub_pred = np.clip(sub_model.predict(sub_scaler.transform(X_test[subset])), 0, 1)
    ablation = {
        "features": len(subset),
        "r2": round(float(r2_score(y_test, sub_pred)), 4),
        "spearman": round(
            float(pd.Series(sub_pred).corr(pd.Series(y_test.values), method="spearman")), 4
        ),
    }

    print(f"\n  selected               {best_name}  (lowest grouped-CV RMSE)")
    print(f"  test RMSE              {best['rmse']:.4f}  (predict-the-mean baseline {baseline_rmse:.4f})")
    print(f"  test R²                {best['r2']:.4f}")
    print(f"  test Spearman          {best['spearman']:.4f}  (old hand-weighted formula {prior_rho:.4f})")
    print(f"  Precision@top-10%      {precision_at_k:.3f}")
    if not beats_baseline:
        print("  WARNING: the model does not beat predicting the mean on the test snapshots.")
    print("\n  importance by signal group (permutation, test set):")
    for group, share in sorted(group_share.items(), key=lambda kv: -kv[1]):
        print(f"    {group:<28}{share:>7.1%}  {'█' * int(share * 50)}")
    print(f"\n  reviews + engagement only ({ablation['features']} features): "
          f"test R² {ablation['r2']:.4f}, Spearman {ablation['spearman']:.4f}")
    print("\n  top features:")
    for name, share in sorted(importances.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {name:<24}{share:>7.1%}")

    # ─── Ship: refit the selected model on every snapshot ────────────────────
    X_all = data[FEATURE_ORDER].astype(float)
    final_scaler = fit_scaler(X_all)
    final_model = candidates[best_name].__class__(**candidates[best_name].get_params())
    final_model.fit(final_scaler.transform(X_all), data["target"])

    ranker = SnapSphereRanker(
        mode="learned", scaler=final_scaler, model=final_model,
        metadata={
            "algorithm": best_name,
            "target": f"percentile of bookings in the next {TARGET_WINDOW_DAYS} days",
            "feature_importance": importances,
            "diagnosis": diagnosis,
        },
    )
    duration = time.perf_counter() - started
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(ranker, ARTIFACT_DIR / "ranker.joblib", compress=3)
    joblib.dump(final_scaler, ARTIFACT_DIR / "scaler.joblib", compress=3)
    print(f"\n  saved                  ranker.joblib (mode=learned, {best_name}, {duration:.1f}s)")

    return {
        "name": "ranker",
        "algorithm": f"{best_name} (learned ranker, temporal training on booking outcomes)",
        "artifact_path": str(ARTIFACT_DIR / "ranker.joblib"),
        "feature_order": FEATURE_ORDER,
        "training_rows": len(data),
        "training_duration_seconds": round(duration, 2),
        "metrics": {
            "mode": "learned",
            "target": f"percentile of bookings in the next {TARGET_WINDOW_DAYS} days",
            "evaluation": f"temporal hold-out: last {TEST_SNAPSHOTS} snapshots; "
                          "model chosen by GroupKFold CV on earlier snapshots",
            "rmse": round(best["rmse"], 4),
            "baseline_rmse": round(baseline_rmse, 4),
            "beats_baseline": bool(beats_baseline),
            "r2": round(best["r2"], 4),
            "spearman": round(best["spearman"], 4),
            "spearman_old_formula": round(prior_rho, 4),
            "precision_at_top_10pct": round(precision_at_k, 3),
            "cv_rmse": {name: round(r["cv_rmse"], 4) for name, r in results.items()},
            "importance_by_group": group_share,
            "reviews_and_engagement_only": ablation,
            "snapshots": n_snap,
        },
        "feature_importance": importances,
    }


if __name__ == "__main__":
    train()
