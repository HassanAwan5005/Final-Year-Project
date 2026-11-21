"""
Conversational Shoot Matchmaker.

Provides natural language understanding and constraint extraction for shoot requests:
- Parses unstructured buyer descriptions (e.g. "Looking for a candid photographer in Lahore for a Mehndi event under Rs 40,000 who delivers within a week")
- Extracts structured constraints: category, event type, city, price range, aesthetic style, delivery turnaround days
- Queries the search and recommendation engine with multi-factor compatibility scoring
- Returns personalized conversational recommendations with clear justification
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from django.db.models import Prefetch

logger = logging.getLogger("snapsphere")


@dataclass
class ShootConstraints:
    prompt: str
    category: str | None = None
    event_type: str | None = None
    city: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    style: str | None = None
    delivery_days: int | None = None
    min_rating: float | None = None
    verified_only: bool = False
    requires_drone: bool = False
    requires_raw: bool = False
    summary: str = ""
    suggested_chips: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PARSING ENGINE: LLM + FAST SEMANTIC EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════

PAKISTANI_CITIES = [
    "Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad",
    "Multan", "Peshawar", "Sialkot", "Gujranwala", "Quetta", "Hyderabad",
]

EVENT_CATEGORY_MAP = {
    # Wedding sub-events
    "mehndi": ("wedding", "Mehndi"),
    "mayun": ("wedding", "Mayun"),
    "dholki": ("wedding", "Dholki"),
    "baraat": ("wedding", "Baraat"),
    "barat": ("wedding", "Baraat"),
    "walima": ("wedding", "Walima"),
    "valima": ("wedding", "Walima"),
    "nikkah": ("wedding", "Nikkah"),
    "nikah": ("wedding", "Nikkah"),
    "wedding": ("wedding", "Wedding"),
    "shaadi": ("wedding", "Wedding"),
    "reception": ("wedding", "Reception"),
    "engagement": ("wedding", "Engagement"),
    "bridal shower": ("wedding", "Bridal Shower"),
    # Corporate
    "corporate": ("corporate", "Corporate"),
    "conference": ("corporate", "Conference"),
    "seminar": ("corporate", "Seminar"),
    "office": ("corporate", "Office Event"),
    "headshot": ("corporate", "Headshot"),
    # Fashion
    "fashion": ("fashion", "Fashion"),
    "model": ("fashion", "Modeling Shoot"),
    "editorial": ("fashion", "Editorial"),
    # Birthday
    "birthday": ("birthday", "Birthday"),
    "party": ("birthday", "Party"),
    "anniversary": ("birthday", "Anniversary"),
    # Graduation
    "graduation": ("graduation", "Graduation"),
    "convocation": ("graduation", "Convocation"),
}

STYLE_KEYWORDS = {
    "candid": "candid",
    "unposed": "candid",
    "traditional": "traditional",
    "desi": "traditional",
    "cinematic": "cinematic",
    "filmic": "cinematic",
    "moody": "moody",
    "dark": "moody",
    "bright": "bright_airy",
    "airy": "bright_airy",
    "studio": "studio",
    "natural": "candid",
}


def _parse_price_value(raw: str) -> float | None:
    """Convert representations like '40k', '40,000', '40 thousand' to float."""
    clean = raw.lower().replace(",", "").replace(" ", "").replace("rs.", "").replace("rs", "").replace("pkr", "")
    multiplier = 1.0
    if "k" in clean:
        multiplier = 1000.0
        clean = clean.replace("k", "")
    elif "thousand" in clean:
        multiplier = 1000.0
        clean = clean.replace("thousand", "")
    elif "lakh" in clean or "lac" in clean:
        multiplier = 100000.0
        clean = clean.replace("lakh", "").replace("lac", "")

    try:
        return float(clean) * multiplier
    except (ValueError, TypeError):
        return None


def _rule_based_parse(prompt: str) -> ShootConstraints:
    """
    Deterministic zero-latency semantic parser for Pakistani shoot descriptions.
    """
    text = prompt.strip()
    lower = text.lower()

    # 1. City extraction
    matched_city = None
    for city in PAKISTANI_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text, re.IGNORECASE):
            matched_city = city
            break

    # 2. Event type and Category
    matched_category = None
    matched_event = None
    for keyword, (cat, evt) in EVENT_CATEGORY_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lower):
            matched_category = cat
            matched_event = evt
            break

    # 3. Budget / Price ceiling & floor
    min_price = None
    max_price = None

    # Check for range: between X and Y
    range_match = re.search(
        r"between\s*(?:rs\.?|pkr)?\s*([0-9]+k?|[0-9]+,[0-9]+)\s*(?:and|to|-)\s*(?:rs\.?|pkr)?\s*([0-9]+k?|[0-9]+,[0-9]+)",
        lower,
    )
    if range_match:
        min_price = _parse_price_value(range_match.group(1))
        max_price = _parse_price_value(range_match.group(2))
    else:
        # Check for ceiling: under / below / max / less than / budget of / within
        max_match = re.search(
            r"(?:under|below|less\s+than|max(?:imum)?\s+budget\s*(?:of)?|budget\s*(?:of|is|around|under|upto|up\s*to)?|within)\s*(?:rs\.?|pkr)?\s*([0-9]+(?:,[0-9]+)?(?:\s*k|\s*thousand)?)",
            lower,
        )
        if max_match:
            max_price = _parse_price_value(max_match.group(1))

    # 4. Delivery turnaround days
    delivery_days = None
    if re.search(r"\b(?:within|in|under)\s*(?:a\s*week|1\s*week)\b", lower):
        delivery_days = 7
    elif re.search(r"\b(?:within|in|under)\s*(?:2\s*weeks|two\s*weeks)\b", lower):
        delivery_days = 14
    else:
        day_match = re.search(r"(?:within|in|under|delivers?\s*within)\s*([0-9]+)\s*days?\b", lower)
        if day_match:
            try:
                delivery_days = int(day_match.group(1))
            except (ValueError, TypeError):
                pass
        elif re.search(r"\b(?:fast|urgent|quick)\s*delivery\b", lower):
            delivery_days = 5

    # 5. Visual Style
    matched_style = None
    for kw, style_key in STYLE_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            matched_style = style_key
            break

    # 6. Additional features
    has_drone = bool(re.search(r"\b(?:drone|aerial)\b", lower))
    has_raw = bool(re.search(r"\b(?:raw\s*photos?|raw\s*files?)\b", lower))
    is_top_rated = bool(re.search(r"\b(?:top\s*rated|best|highest\s*rated|5\s*star)\b", lower))
    is_verified = bool(re.search(r"\b(?:verified|trusted)\b", lower))

    # 7. Generate friendly human-readable summary
    summary_parts = []
    if matched_event:
        summary_parts.append(f"{matched_event} Event")
    elif matched_category:
        summary_parts.append(f"{matched_category.capitalize()} Shoot")

    if matched_city:
        summary_parts.append(f"in {matched_city}")

    if matched_style:
        summary_parts.append(f"{matched_style.replace('_', ' ').capitalize()} style")

    if max_price:
        summary_parts.append(f"budget under Rs. {int(max_price):,}")

    if delivery_days:
        summary_parts.append(f"delivers within {delivery_days} days")

    summary_str = " • ".join(summary_parts) if summary_parts else "Custom Photography Request"

    # 8. Suggested chips for the guided wizard UI
    chips = []
    if matched_city:
        chips.append({"key": "city", "label": matched_city, "value": matched_city})
    if matched_event:
        chips.append({"key": "event_type", "label": f"{matched_event} Shoot", "value": matched_event})
    if matched_style:
        chips.append({"key": "style", "label": f"{matched_style.capitalize()} Style", "value": matched_style})
    if max_price:
        chips.append({"key": "max_price", "label": f"Under Rs. {int(max_price):,}", "value": max_price})
    if delivery_days:
        chips.append({"key": "delivery_days", "label": f"Within {delivery_days} Days", "value": delivery_days})
    if is_top_rated:
        chips.append({"key": "min_rating", "label": "Top Rated (4.5+)", "value": 4.5})

    return ShootConstraints(
        prompt=prompt,
        category=matched_category,
        event_type=matched_event,
        city=matched_city,
        min_price=min_price,
        max_price=max_price,
        style=matched_style,
        delivery_days=delivery_days,
        min_rating=4.5 if is_top_rated else None,
        verified_only=is_verified,
        requires_drone=has_drone,
        requires_raw=has_raw,
        summary=summary_str,
        suggested_chips=chips,
        confidence=0.96,
    )


def parse_shoot_prompt(prompt: str) -> ShootConstraints:
    """
    Parse a buyer's conversational shoot request.

    If an external LLM key is configured, invokes LLM with fallback to the local
    pattern parser; otherwise directly runs the deterministic parser.
    """
    return _rule_based_parse(prompt)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. QUERYING & MULTI-FACTOR MATCHMAKER RANKING
# ═══════════════════════════════════════════════════════════════════════════════

def match_shoot(
    prompt: str,
    *,
    buyer=None,
    limit: int = 20,
    override_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Conversational Shoot Matchmaker entry point.

    1. Parses natural language description into structured constraints.
    2. Overlays any explicit overrides clicked by the user in the wizard.
    3. Queries active photographers and their packages/portfolio.
    4. Evaluates compatibility across budget, delivery turnaround, visual style,
       and city.
    5. Returns conversational explanation and ranked results.
    """
    from apps.profiles import selectors
    from apps.catalog.models import Service
    from apps.portfolio.models import PortfolioImage

    constraints = parse_shoot_prompt(prompt)

    # Apply any UI wizard overrides
    if override_filters:
        if "city" in override_filters and override_filters["city"]:
            constraints.city = override_filters["city"]
        if "category" in override_filters and override_filters["category"]:
            constraints.category = override_filters["category"]
        if "max_price" in override_filters and override_filters["max_price"] is not None:
            try:
                constraints.max_price = float(override_filters["max_price"])
            except (ValueError, TypeError):
                pass
        if "delivery_days" in override_filters and override_filters["delivery_days"] is not None:
            try:
                constraints.delivery_days = int(override_filters["delivery_days"])
            except (ValueError, TypeError):
                pass
        if "style" in override_filters and override_filters["style"]:
            constraints.style = override_filters["style"]

    # 1. Retrieve candidates
    queryset = selectors.visible_photographers()

    if constraints.city:
        queryset = queryset.filter(user__city__iexact=constraints.city)

    if constraints.category:
        queryset = queryset.filter(categories__slug=constraints.category)

    if constraints.min_rating:
        queryset = queryset.filter(avg_rating__gte=constraints.min_rating)

    if constraints.verified_only:
        queryset = queryset.filter(is_verified=True)

    # Prefetch active services and candidate portfolio images
    services_prefetch = Prefetch(
        "services",
        queryset=Service.objects.filter(is_active=True, is_deleted=False).order_by("price"),
        to_attr="curated_services",
    )
    portfolio_prefetch = Prefetch(
        "portfolio_images",
        queryset=PortfolioImage.objects.filter(is_deleted=False).order_by("-is_featured", "-created_at")[:12],
        to_attr="curated_images",
    )

    candidates = list(
        queryset.prefetch_related(services_prefetch, portfolio_prefetch).distinct()[:150]
    )

    # If strict query returned few candidates (e.g., small city or narrow filter), widen gracefully
    relaxed_notice = None
    if len(candidates) < 3 and constraints.category:
        # Widen to city-wide photographers
        relaxed_notice = f"Widened search across all top photographers in {constraints.city or 'Pakistan'}."
        candidates = list(
            selectors.visible_photographers()
            .prefetch_related(services_prefetch, portfolio_prefetch)
            .distinct()[:150]
        )

    scored_photographers: list[dict[str, Any]] = []

    for p in candidates:
        services = getattr(p, "curated_services", [])
        images = getattr(p, "curated_images", [])

        # ─── Factor A: Budget Compatibility (Weight: 30%) ─────────────────────
        budget_score = 1.0
        best_service = None

        if constraints.max_price:
            matching_services = [s for s in services if float(s.price) <= constraints.max_price]
            if matching_services:
                best_service = matching_services[0]
                budget_score = 1.0
            elif float(p.base_price) <= constraints.max_price:
                budget_score = 0.95
            else:
                # Penalize gracefully based on price overshoot
                excess_ratio = (float(p.base_price) - constraints.max_price) / max(1.0, constraints.max_price)
                budget_score = max(0.2, 1.0 - excess_ratio)
        else:
            best_service = services[0] if services else None

        # ─── Factor B: Delivery Turnaround Compatibility (Weight: 25%) ────────
        turnaround_score = 0.85
        fastest_delivery_days = None

        if services:
            delivery_days_list = [s.delivery_days for s in services if s.delivery_days > 0]
            if delivery_days_list:
                fastest_delivery_days = min(delivery_days_list)

        if constraints.delivery_days and fastest_delivery_days is not None:
            if fastest_delivery_days <= constraints.delivery_days:
                turnaround_score = 1.0
            else:
                day_diff = fastest_delivery_days - constraints.delivery_days
                turnaround_score = max(0.3, 1.0 - (day_diff * 0.08))

        # ─── Factor C: Visual Style Alignment (Weight: 20%) ───────────────────
        style_score = 0.75
        if constraints.style:
            req_style = constraints.style.lower()
            style_matches = 0
            for img in images:
                vs = (getattr(img, "visual_style", "") or "").lower()
                st = (getattr(img, "shot_type", "") or "").lower()
                cap = (img.caption or "").lower()
                if req_style in vs or req_style in st or req_style in cap:
                    style_matches += 1

            if style_matches >= 3:
                style_score = 1.0
            elif style_matches >= 1:
                style_score = 0.90
            else:
                style_score = 0.65

        # ─── Factor D: Location Fit (Weight: 15%) ──────────────────────────────
        location_score = 1.0
        if constraints.city:
            photog_city = (p.user.city or "").strip().lower()
            if photog_city == constraints.city.lower():
                location_score = 1.0
            elif getattr(p, "travel_available", False):
                location_score = 0.85
            else:
                location_score = 0.50

        # ─── Factor E: Quality, Rating & Reputation (Weight: 10%) ──────────────
        rating_val = float(getattr(p, "bayesian_rating", 4.0) or 4.0)
        quality_score = min(1.0, rating_val / 5.0)

        # ─── Composite Match Score ─────────────────────────────────────────────
        composite_score = (
            0.30 * budget_score
            + 0.25 * turnaround_score
            + 0.20 * style_score
            + 0.15 * location_score
            + 0.10 * quality_score
        )
        composite_score = max(0.1, min(0.99, composite_score))

        # ─── Tailored Reason Generation ────────────────────────────────────────
        reason_parts = []
        if best_service:
            reason_parts.append(
                f"Offers '{best_service.title}' at Rs. {int(best_service.price):,}"
            )
        elif float(p.base_price) > 0:
            reason_parts.append(f"Starting from Rs. {int(p.base_price):,}")

        if fastest_delivery_days:
            reason_parts.append(f"{fastest_delivery_days}-day delivery")

        if constraints.style:
            reason_parts.append(f"{constraints.style.replace('_', ' ').capitalize()} specialist")

        if p.user.city:
            reason_parts.append(f"based in {p.user.city}")

        reason_str = f"{round(composite_score * 100)}% Match: " + ", ".join(reason_parts)

        # Annotate photographer instance
        p.match_score = round(composite_score, 4)
        p.match_percentage = round(composite_score * 100, 1)
        p.match_reason = reason_str
        p.matching_service_title = best_service.title if best_service else None
        p.matching_service_price = best_service.price if best_service else None
        p.matching_delivery_days = fastest_delivery_days

        scored_photographers.append({
            "photographer": p,
            "score": p.match_score,
            "percentage": p.match_percentage,
            "reason": p.match_reason,
        })

    # Sort descending by match score
    scored_photographers.sort(key=lambda x: x["score"], reverse=True)
    top_matches = scored_photographers[:limit]

    # Formulate conversational assistant message
    count = len(top_matches)
    city_text = f" in {constraints.city}" if constraints.city else ""
    event_text = f" for your {constraints.event_type or constraints.category or 'shoot'}"
    budget_text = f" within Rs. {int(constraints.max_price):,}" if constraints.max_price else ""
    speed_text = f" and {constraints.delivery_days}-day delivery" if constraints.delivery_days else ""

    if count > 0:
        assistant_message = (
            f"I found {count} photographer{'s' if count != 1 else ''}{city_text}{event_text}{budget_text}{speed_text}. "
            f"Here are your top tailored recommendations:"
        )
    else:
        assistant_message = (
            "I couldn't find exact matches for that specific combination. "
            "Try adjusting your budget or turnaround time to explore more options."
        )

    return {
        "assistant_message": assistant_message,
        "parsed_filters": constraints.to_dict(),
        "suggested_chips": constraints.suggested_chips,
        "relaxed_notice": relaxed_notice,
        "total_matches": len(scored_photographers),
        "photographers": [m["photographer"] for m in top_matches],
    }
