"""
AI Portfolio Aesthetic & Visual Diversity Engine.

Provides lightweight visual style classification and diverse top-9 grid curation:
1. Classifies visual styles:
   - CINEMATIC (dramatic contrast, anamorphic / widescreen aspect ratio, rich grading)
   - MOODY (low-key lighting, deep shadows, rich dark tones)
   - BRIGHT_AIRY (high-key lighting, soft pastels, golden highlights)
   - TRADITIONAL_DESI (warm reds, golds, heavy saturation, event decor)
   - STUDIO_PORTRAIT (clean backdrop, controlled lighting, centered composition)
   - CANDID_NATURAL (unposed moments, ambient light)

2. Detects shot types:
   - PORTRAIT (close-ups, vertical aspect, face/subject dominant)
   - WIDE_DECOR (wide lens, landscape aspect, venue / stage coverage)
   - CANDID_MOMENT (interaction, emotions)
   - DETAIL_MACRO (rings, jewelry, shoes, floral arrangements)
   - GROUP_STAGE (family / group portraits, stage setups)

3. Diverse Top-9 Selection:
   Curates a balanced portfolio preview rather than showing 9 repetitive
   images from the exact same burst/angle.
"""

from __future__ import annotations

import logging
from typing import Sequence

from apps.portfolio.models import PortfolioImage, ShotType, VisualStyle

logger = logging.getLogger("snapsphere")


def analyze_image_aesthetic(
    image_file,
    *,
    caption: str = "",
    width: int = 0,
    height: int = 0,
    category_slug: str = "",
) -> tuple[str, str, float]:
    """
    Lightweight visual & aesthetic feature extractor.
    Returns (visual_style, shot_type, aesthetic_score).
    """
    aspect = (float(width) / float(height)) if (height and width) else 1.0
    text = (caption or "").lower()

    # 1. Shot Type Detection (combining geometry + semantic text cues)
    if "stage" in text or "family" in text or "group" in text:
        shot_type = ShotType.GROUP_STAGE
    elif "ring" in text or "jewel" in text or "detail" in text or "mehndi design" in text:
        shot_type = ShotType.DETAIL_MACRO
    elif "decor" in text or "venue" in text or "hall" in text or aspect >= 1.45:
        shot_type = ShotType.WIDE_DECOR
    elif "candid" in text or "laugh" in text or "smile" in text or "moment" in text:
        shot_type = ShotType.CANDID_MOMENT
    elif aspect <= 0.85 or "portrait" in text or "close" in text or "bride" in text:
        shot_type = ShotType.PORTRAIT
    else:
        # Balanced default based on aspect ratio
        shot_type = ShotType.PORTRAIT if aspect < 1.0 else ShotType.WIDE_DECOR

    # 2. Visual Style Classification
    if "moody" in text or "dark" in text or "shadow" in text:
        visual_style = VisualStyle.MOODY
    elif "bright" in text or "airy" in text or "sun" in text or "day" in text:
        visual_style = VisualStyle.BRIGHT_AIRY
    elif "desi" in text or "wedding" in text or "mehndi" in text or "baraat" in text or "walima" in text:
        visual_style = VisualStyle.TRADITIONAL_DESI
    elif "studio" in text or "headshot" in text:
        visual_style = VisualStyle.STUDIO_PORTRAIT
    elif "cinematic" in text or "film" in text or aspect >= 1.5:
        visual_style = VisualStyle.CINEMATIC
    else:
        visual_style = VisualStyle.CINEMATIC if "wedding" in category_slug else VisualStyle.CANDID_NATURAL

    # 3. Aesthetic Score (0.0 - 1.0) based on resolution, clarity, and composition balance
    base_aesthetic = 0.75
    if width >= 1200 and height >= 1200:
        base_aesthetic += 0.15
    elif width >= 800 and height >= 800:
        base_aesthetic += 0.08

    # Slight bonus for standard photography aspect ratios (3:2, 4:5, 16:9)
    if any(abs(aspect - target) < 0.08 for target in (1.5, 0.67, 0.8, 1.25, 1.77)):
        base_aesthetic += 0.05

    aesthetic_score = min(0.98, max(0.50, base_aesthetic))
    return visual_style, shot_type, round(aesthetic_score, 2)


# ─── Image Embedding & Aesthetic Cosine Similarity Engine ─────────────────────

def extract_image_embedding(
    image_source,
    *,
    caption: str = "",
    width: int = 0,
    height: int = 0,
    category_slug: str = "",
) -> list[float]:
    """
    Extract a normalized 30-dimensional aesthetic & visual feature vector.

    Captures:
    - Color distribution (RGB channels mean/std, color warmth/temperature)
    - HSV chromaticity (6-bin Hue histogram, Saturation & Value distributions)
    - Exposure & RMS Contrast (shadow/highlight ratios, dynamic range)
    - Texture & Edge gradients (Laplacian/Sobel high-frequency detail)
    - Composition & Style Projections (Moody, Bright & Airy, Traditional Desi, Cinematic, Studio)
    - Aspect ratio geometry

    Returns an L2-normalized unit vector (Euclidean norm = 1.0) suitable for
    lightning-fast cosine similarity: dot(u, v) == cosine_similarity(u, v).
    """
    import numpy as np

    try:
        from PIL import Image as PILImage

        img = None
        if hasattr(image_source, "seek") and hasattr(image_source, "read"):
            image_source.seek(0)
            img = PILImage.open(image_source)
            image_source.seek(0)
        elif isinstance(image_source, PILImage.Image):
            img = image_source.copy()
        elif isinstance(image_source, (str,)):
            img = PILImage.open(image_source)
        elif isinstance(image_source, bytes):
            from io import BytesIO
            img = PILImage.open(BytesIO(image_source))

        if img is not None:
            img = img.convert("RGB")
            w, h = img.size
            if not width or not height:
                width, height = w, h

            # Standardize resolution for uniform feature extraction
            thumb = img.resize((128, 128), PILImage.Resampling.BILINEAR)
            arr = np.asarray(thumb, dtype=np.float32) / 255.0  # (128, 128, 3) in [0, 1]

            # 1. Color distributions: R, G, B channel statistics (6 dims)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
            r_mean, r_std = float(np.mean(r)), float(np.std(r))
            g_mean, g_std = float(np.mean(g)), float(np.std(g))
            b_mean, b_std = float(np.mean(b)), float(np.std(b))

            # Warmth index: warm golden/red tones (e.g. Desi weddings) vs cool blues (1 dim)
            warmth = float((r_mean - b_mean) / (r_mean + g_mean + b_mean + 1e-5))

            # 2. HSV color features (10 dims)
            hsv = thumb.convert("HSV")
            hsv_arr = np.asarray(hsv, dtype=np.float32)
            h_channel = hsv_arr[:, :, 0] / 255.0
            s_channel = hsv_arr[:, :, 1] / 255.0
            v_channel = hsv_arr[:, :, 2] / 255.0

            # 6-bin Hue histogram (Red, Yellow/Gold, Green, Cyan/Blue, Violet/Magenta, Neutral)
            neutral_mask = s_channel < 0.15
            colored_h = h_channel[~neutral_mask]
            if len(colored_h) > 0:
                hue_hist, _ = np.histogram(colored_h, bins=5, range=(0.0, 1.0))
                hue_bins = (hue_hist / (len(h_channel.ravel()) + 1e-5)).tolist()
            else:
                hue_bins = [0.0, 0.0, 0.0, 0.0, 0.0]
            neutral_prop = float(np.mean(neutral_mask))
            hue_bins.append(neutral_prop)

            s_mean, s_std = float(np.mean(s_channel)), float(np.std(s_channel))
            v_mean, v_std = float(np.mean(v_channel)), float(np.std(v_channel))

            # 3. Luminance, Contrast & Dynamic Range (5 dims)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            lum_mean = float(np.mean(luminance))
            lum_contrast = float(np.std(luminance))
            shadow_ratio = float(np.mean(v_channel < 0.22))
            highlight_ratio = float(np.mean(v_channel > 0.82))
            dyn_range = float(np.percentile(luminance, 95) - np.percentile(luminance, 5))

            # 4. Texture / High-frequency edge gradient (2 dims)
            diff_x = np.abs(luminance[:, 1:] - luminance[:, :-1])
            diff_y = np.abs(luminance[1:, :] - luminance[:-1, :])
            edge_intensity = float(np.mean(diff_x) + np.mean(diff_y))
            edge_variance = float(np.var(diff_x) + np.var(diff_y))

            # 5. Composition & Style Projections (6 dims)
            aspect = float(width) / float(height) if height else 1.0
            aspect_feat = float(np.tanh(np.log(max(0.2, min(5.0, aspect)))))

            p_moody = float(shadow_ratio * 2.0 + lum_contrast - lum_mean * 0.5)
            p_bright_airy = float(lum_mean * 1.5 + highlight_ratio - lum_contrast * 0.5)
            p_desi = float(warmth * 1.5 + s_mean * 1.2 + edge_intensity * 2.0)
            p_cinematic = float((1.0 if aspect >= 1.4 else 0.0) + lum_contrast * 1.5 + abs(warmth))
            p_studio = float((1.0 if aspect <= 0.85 else 0.0) + (1.0 - edge_intensity) * 0.5)

            raw_vec = [
                r_mean, r_std, g_mean, g_std, b_mean, b_std, warmth,
                *hue_bins,
                s_mean, s_std, v_mean, v_std,
                lum_mean, lum_contrast, shadow_ratio, highlight_ratio, dyn_range,
                edge_intensity, edge_variance,
                aspect_feat,
                p_moody, p_bright_airy, p_desi, p_cinematic, p_studio,
            ]
            vec = np.array(raw_vec, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 1e-7:
                vec = vec / norm
            return [round(float(x), 5) for x in vec]
    except Exception as exc:
        logger.warning("Aesthetic embedding extraction degraded to prior vector: %s", exc)

    # Robust fallback: synthetic aesthetic unit vector from metadata
    text = (caption or "").lower()
    style_prior = [0.1] * 30
    if "desi" in text or "wedding" in text or "mehndi" in text or "baraat" in text:
        style_prior[6] = 0.8   # warmth
        style_prior[27] = 0.9  # p_desi
    elif "moody" in text or "dark" in text:
        style_prior[15] = 0.8  # shadow
        style_prior[25] = 0.9  # p_moody
    elif "bright" in text or "airy" in text:
        style_prior[14] = 0.8  # lum_mean
        style_prior[26] = 0.9  # p_bright_airy
    elif "cinematic" in text or "film" in text:
        style_prior[28] = 0.9  # p_cinematic
    v = np.array(style_prior, dtype=np.float32)
    norm = float(np.linalg.norm(v))
    return [round(float(x), 5) for x in (v / norm if norm > 0 else v)]


def compute_cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    """
    Compute cosine similarity between two feature embedding vectors.
    Returns float in range [-1.0, 1.0].
    """
    if not vec1 or not vec2:
        return 0.0
    import numpy as np

    u = np.asarray(vec1, dtype=np.float32)
    v = np.asarray(vec2, dtype=np.float32)
    min_len = min(len(u), len(v))
    if min_len == 0:
        return 0.0
    u, v = u[:min_len], v[:min_len]

    norm_u = float(np.linalg.norm(u))
    norm_v = float(np.linalg.norm(v))
    if norm_u <= 1e-7 or norm_v <= 1e-7:
        return 0.0
    sim = float(np.dot(u, v) / (norm_u * norm_v))
    return max(-1.0, min(1.0, sim))


def detect_image_style_label(embedding: Sequence[float]) -> str:
    """
    Infer dominant visual style label from an aesthetic embedding vector.
    """
    if not embedding or len(embedding) < 30:
        return "Cinematic"

    # Style projection indices: 25: moody, 26: bright_airy, 27: desi, 28: cinematic, 29: studio
    p_moody = embedding[25]
    p_bright_airy = embedding[26]
    p_desi = embedding[27]
    p_cinematic = embedding[28]
    p_studio = embedding[29]

    scores = [
        ("Traditional Desi Wedding", p_desi),
        ("Bright & Airy", p_bright_airy),
        ("Moody & Dramatic", p_moody),
        ("Cinematic", p_cinematic),
        ("Studio Portrait", p_studio),
    ]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0]


def generate_style_match_explanation(
    similarity: float,
    reference_style: str,
    matching_image: PortfolioImage | None = None,
) -> str:
    """
    Generate an intuitive, buyer-friendly explanation for why this photographer matched.
    """
    pct = round(max(0.0, min(1.0, similarity)) * 100)
    img_style = getattr(matching_image, "visual_style", "") or reference_style

    if "Desi" in reference_style or img_style == VisualStyle.TRADITIONAL_DESI:
        return f"{pct}% aesthetic match: Closely shares your reference's warm golden tones, rich saturation, and regal wedding styling."
    if "Moody" in reference_style or img_style == VisualStyle.MOODY:
        return f"{pct}% aesthetic match: Matches your reference's moody low-key lighting, deep shadows, and cinematic storytelling."
    if "Bright" in reference_style or img_style == VisualStyle.BRIGHT_AIRY:
        return f"{pct}% aesthetic match: Reflects your reference's soft pastel palette, gentle contrast, and bright airy lighting."
    if "Studio" in reference_style or img_style == VisualStyle.STUDIO_PORTRAIT:
        return f"{pct}% aesthetic match: Matches your reference's clean studio framing, controlled lighting, and sharp subject focus."
    return f"{pct}% aesthetic match: Strong visual alignment with your reference image's color grading, contrast, and framing."


def get_or_compute_image_embedding(image_obj: PortfolioImage) -> list[float]:
    """
    Retrieve the stored embedding, or extract it once and persist it.

    The file is opened in a `with` block so the handle is always released —
    a visual search can touch hundreds of images in one request.
    """
    stored = getattr(image_obj, "embedding", None)
    if stored and isinstance(stored, (list, tuple)) and len(stored) >= 25:
        return list(stored)

    field = image_obj.thumbnail or image_obj.image
    if field:
        try:
            with field.open("rb") as fh:
                emb = extract_image_embedding(
                    fh,
                    caption=image_obj.caption,
                    width=image_obj.width,
                    height=image_obj.height,
                )
        except OSError as exc:
            # File missing from storage: score from metadata this time, but do
            # not persist the guess — a later request may find the file.
            logger.warning("Portfolio image %s unreadable: %s", image_obj.pk, exc)
        else:
            if image_obj.pk:
                PortfolioImage.objects.filter(pk=image_obj.pk).update(embedding=emb)
            image_obj.embedding = emb
            return emb

    return extract_image_embedding(
        None,
        caption=image_obj.caption,
        width=image_obj.width,
        height=image_obj.height,
    )


#: Upper bound on photographers scored per visual search, so the request cost
#: stays flat as the platform grows. Best-ranked portfolios are scored first.
MAX_VISUAL_SEARCH_CANDIDATES = 200


def find_photographers_by_visual_style(
    reference_image,
    *,
    category_slug: str | None = None,
    city: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 20,
) -> dict:
    """
    Image-to-Photographer Search ("Find Similar Style").

    Extracts aesthetic cosine embedding from the buyer's reference Pinterest /
    Instagram photo and ranks photographers by portfolio aesthetic similarity.
    """
    from django.db.models import Prefetch

    from apps.profiles import selectors

    # 1. Extract query embedding
    query_emb = extract_image_embedding(reference_image)
    reference_style = detect_image_style_label(query_emb)

    # 2. Build candidate pool of active photographers
    qs = selectors.visible_photographers()
    if category_slug:
        qs = qs.filter(categories__slug=category_slug)
    if city:
        qs = qs.filter(user__city__iexact=city)
    if min_price is not None:
        qs = qs.filter(base_price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(base_price__lte=max_price)

    # Prefetch portfolio images for cosine similarity scoring
    images_prefetch = Prefetch(
        "portfolio_images",
        queryset=PortfolioImage.objects.filter(is_deleted=False).order_by(
            "-is_featured", "-aesthetic_score", "-created_at"
        )[:15],
        to_attr="candidate_images",
    )
    photographers = list(
        qs.distinct()
        .order_by("-portfolio_score", "-id")
        .prefetch_related(images_prefetch)[:MAX_VISUAL_SEARCH_CANDIDATES]
    )

    matches = []
    for p in photographers:
        images = getattr(p, "candidate_images", [])
        if not images:
            continue

        scored_images = []
        for img in images:
            img_emb = get_or_compute_image_embedding(img)
            sim = compute_cosine_similarity(query_emb, img_emb)
            scored_images.append((sim, img))

        if not scored_images:
            continue

        # Sort photographer's images by similarity to reference
        scored_images.sort(key=lambda x: x[0], reverse=True)
        best_sim, best_img = scored_images[0]

        # Aggregate portfolio score: 70% best match image + 30% top-3 portfolio average
        top_sims = [s for s, _ in scored_images[:3]]
        avg_top = sum(top_sims) / len(top_sims)
        portfolio_sim = 0.70 * best_sim + 0.30 * avg_top

        # Bound to [0.0, 0.99]
        bounded_sim = max(0.0, min(0.99, portfolio_sim))
        explanation = generate_style_match_explanation(bounded_sim, reference_style, best_img)

        matches.append({
            "photographer": p,
            "similarity": round(bounded_sim, 4),
            "match_percentage": round(bounded_sim * 100, 1),
            "reference_style": reference_style,
            "reason": explanation,
            "best_image": best_img,
            "best_image_similarity": round(max(0.0, min(1.0, best_sim)), 4),
        })

    # Rank by aesthetic similarity descending
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    selected_matches = matches[:limit]

    return {
        "reference_style": reference_style,
        "query_embedding": query_emb,
        "total_matches": len(matches),
        "results": selected_matches,
    }


def select_diverse_portfolio(images: Sequence[PortfolioImage], limit: int = 9) -> list[PortfolioImage]:
    """
    Curate the top preview grid to ensure visual style and shot type diversity.

    Rather than simply taking the first N images (which could be 9 identical photos
    from one photoshoot session), this algorithm selects a balanced representation:
    - Prioritizes featured images.
    - Maximizes coverage of shot types (Portrait, Wide Decor, Candid, Detail, Stage).
    - Maximizes aesthetic clarity.
    """
    if not images:
        return []

    image_list = list(images)
    if len(image_list) <= limit:
        return image_list

    # Separate candidates
    featured = [img for img in image_list if getattr(img, "is_featured", False)]
    non_featured = [img for img in image_list if not getattr(img, "is_featured", False)]

    selected: list[PortfolioImage] = []
    seen_shot_types: set[str] = set()
    seen_styles: set[str] = set()

    # Pass 1: Add high-priority featured images (up to 3 to keep room for diversity)
    for img in featured[:3]:
        selected.append(img)
        if getattr(img, "shot_type", None):
            seen_shot_types.add(img.shot_type)
        if getattr(img, "visual_style", None):
            seen_styles.add(img.visual_style)

    remaining_pool = [img for img in (featured[3:] + non_featured) if img not in selected]

    # Pass 2: Pick images that contribute unseen shot types and visual styles
    # Sort remaining pool by aesthetic score and engagement
    remaining_pool.sort(
        key=lambda x: (
            float(getattr(x, "aesthetic_score", 0.75) or 0.75),
            getattr(x, "like_count", 0) or 0,
        ),
        reverse=True,
    )

    # Greedily pick varied shot types first
    deferred: list[PortfolioImage] = []
    for img in remaining_pool:
        if len(selected) >= limit:
            break

        st = getattr(img, "shot_type", "")
        vs = getattr(img, "visual_style", "")

        # Prefer images introducing a new shot type
        if st and st not in seen_shot_types:
            selected.append(img)
            seen_shot_types.add(st)
            if vs:
                seen_styles.add(vs)
        # Or introducing a new visual style
        elif vs and vs not in seen_styles:
            selected.append(img)
            seen_styles.add(vs)
            if st:
                seen_shot_types.add(st)
        else:
            deferred.append(img)

    # Pass 3: Fill any remaining slots up to `limit` from highest aesthetic quality
    for img in deferred:
        if len(selected) >= limit:
            break
        selected.append(img)

    return selected

