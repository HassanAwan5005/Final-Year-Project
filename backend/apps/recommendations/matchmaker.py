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

from django.db.models import Exists, OuterRef, Prefetch

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
    # Recognised even with no photographer there yet, so the buyer is told
    # "no photographers in Gujrat" instead of silently getting all of Pakistan.
    "Gujrat", "Bahawalpur", "Sargodha", "Sukkur", "Larkana", "Sheikhupura",
    "Rahim Yar Khan", "Jhang", "Dera Ghazi Khan", "Sahiwal", "Wah Cantt",
    "Mardan", "Kasur", "Okara", "Mingora", "Nawabshah", "Chiniot", "Kamoke",
    "Sadiqabad", "Burewala", "Jacobabad", "Muzaffargarh", "Abbottabad",
    "Mirpur", "Muzaffarabad", "Gilgit", "Skardu", "Murree", "Jhelum",
    "Mandi Bahauddin", "Khanewal", "Hafizabad", "Kohat", "Attock", "Gwadar",
    "Mansehra", "Swat", "Chakwal", "Vehari", "Mianwali", "Taxila",
]

# Words a buyer uses → (category slug, event label). The slugs are the five
# photographer categories: wedding, corporate, fashion, birthday, graduation.
# Checked in this order, so "office party" is corporate and "wedding party" is
# a wedding. Plurals match too ("companies", "walimas").
EVENT_CATEGORY_MAP = {
    # Wedding and its events
    "mehndi": ("wedding", "Mehndi"),
    "mehendi": ("wedding", "Mehndi"),
    "mehandi": ("wedding", "Mehndi"),
    "mayun": ("wedding", "Mayun"),
    "mayon": ("wedding", "Mayun"),
    "mayoon": ("wedding", "Mayun"),
    "dholki": ("wedding", "Dholki"),
    "dholak": ("wedding", "Dholki"),
    "baraat": ("wedding", "Baraat"),
    "barat": ("wedding", "Baraat"),
    "rukhsati": ("wedding", "Rukhsati"),
    "walima": ("wedding", "Walima"),
    "valima": ("wedding", "Walima"),
    "nikkah": ("wedding", "Nikkah"),
    "nikah": ("wedding", "Nikkah"),
    "wedding": ("wedding", "Wedding"),
    "shaadi": ("wedding", "Wedding"),
    "shadi": ("wedding", "Wedding"),
    "marriage": ("wedding", "Wedding"),
    "reception": ("wedding", "Reception"),
    "engagement": ("wedding", "Engagement"),
    "mangni": ("wedding", "Engagement"),
    "sangeet": ("wedding", "Sangeet"),
    "bridal shower": ("wedding", "Bridal Shower"),
    "bridal": ("wedding", "Bridal"),
    "bride": ("wedding", "Wedding"),
    "groom": ("wedding", "Wedding"),
    "dulha": ("wedding", "Wedding"),
    "dulhan": ("wedding", "Wedding"),
    # Corporate
    "corporate": ("corporate", "Corporate"),
    "company": ("corporate", "Corporate"),
    "companies": ("corporate", "Corporate"),
    "organization": ("corporate", "Corporate"),
    "organisation": ("corporate", "Corporate"),
    "office": ("corporate", "Office Event"),
    "ceo": ("corporate", "Corporate"),
    "executive": ("corporate", "Corporate"),
    "business": ("corporate", "Corporate"),
    "firm": ("corporate", "Corporate"),
    "startup": ("corporate", "Corporate"),
    "employee": ("corporate", "Corporate"),
    "staff": ("corporate", "Corporate"),
    "conference": ("corporate", "Conference"),
    "seminar": ("corporate", "Seminar"),
    "workshop": ("corporate", "Workshop"),
    "product launch": ("corporate", "Product Launch"),
    "launch event": ("corporate", "Product Launch"),
    "headshot": ("corporate", "Headshot"),
    "linkedin": ("corporate", "Headshot"),
    # Fashion
    "fashion": ("fashion", "Fashion"),
    "model": ("fashion", "Modeling Shoot"),
    "modeling": ("fashion", "Modeling Shoot"),
    "modelling": ("fashion", "Modeling Shoot"),
    "editorial": ("fashion", "Editorial"),
    "lookbook": ("fashion", "Lookbook"),
    "catalogue": ("fashion", "Catalogue Shoot"),
    "catalog": ("fashion", "Catalogue Shoot"),
    "runway": ("fashion", "Runway"),
    "ramp": ("fashion", "Runway"),
    "designer": ("fashion", "Fashion"),
    "clothing": ("fashion", "Fashion"),
    "apparel": ("fashion", "Fashion"),
    "boutique": ("fashion", "Fashion"),
    # Birthday and celebrations
    "birthday": ("birthday", "Birthday"),
    "bday": ("birthday", "Birthday"),
    "party": ("birthday", "Party"),
    "anniversary": ("birthday", "Anniversary"),
    "baby shower": ("birthday", "Baby Shower"),
    "cake smash": ("birthday", "Birthday"),
    # Graduation
    "graduation": ("graduation", "Graduation"),
    "graduate": ("graduation", "Graduation"),
    "convocation": ("graduation", "Convocation"),
    "university": ("graduation", "Graduation"),
    "college": ("graduation", "Graduation"),
    "degree": ("graduation", "Graduation"),
    "farewell": ("graduation", "Farewell"),
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


# Short names people type for a city.
CITY_ALIASES = {
    "pindi": "Rawalpindi",
    "isb": "Islamabad",
    "khi": "Karachi",
    "lhr": "Lahore",
    "fsd": "Faisalabad",
}


def _known_cities() -> list[str]:
    """
    Every city a photographer can be in: the built-in list plus whatever cities
    photographers actually registered with. Without the second part, a buyer
    who names a city outside the list gets no city filter at all, and so sees
    photographers from everywhere.
    """
    cities = {c.lower(): c for c in PAKISTANI_CITIES}
    try:
        from apps.accounts.models import User
        from apps.core.constants import UserRole

        rows = (
            User.objects.filter(role=UserRole.PHOTOGRAPHER)
            .exclude(city="")
            .values_list("city", flat=True)
            .distinct()
        )
        for city in rows:
            name = city.strip()
            if name:
                cities.setdefault(name.lower(), name)
    except Exception:  # noqa: BLE001 — parsing must still work without a database
        logger.debug("matchmaker: could not load cities from the database", exc_info=True)
    return list(cities.values())


def _find_city(text: str) -> str | None:
    """The city named in the request. Longer names win, so a city whose name
    contains a shorter one is not mistaken for it."""
    for city in sorted(_known_cities(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(city)}\b", text, re.IGNORECASE):
            return city
    for alias, city in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return city
    return None


# An amount of money: optional currency, a number (Pakistani "1,50,000" and
# decimals like "1.5" allowed), optional multiplier. It must not be followed by
# a unit that makes it something else — "within 7 days" is a delivery time, not
# a budget of Rs 7.
_CURRENCY = r"(?:rs\.?|pkr|rupees?)"
_MULTIPLIER = r"(?:k|thousand|lakhs?|lacs?)"
_NOT_MONEY = r"(?!\s*(?:days?|weeks?|months?|years?|hours?|hrs?|h\b|mins?|minutes?|photos?|pictures?|pics?|images?|people|persons?|guests?|stars?|km|videos?|resolution)\b)"
_AMOUNT = (
    rf"(?P<cur>{_CURRENCY}\s*)?"
    rf"(?P<num>\d+(?:[.,]\d+)*)(?![.,]?\d)"
    rf"\s*(?P<mul>{_MULTIPLIER}\b)?"
    rf"(?:\s*{_CURRENCY})?"
    rf"{_NOT_MONEY}"
)


def _parse_price_value(raw: str) -> float | None:
    """Convert '40k', '40,000', '1,50,000', '1.5 lakh', 'Rs 40000' to a float."""
    clean = raw.lower()
    for word in ("rupees", "rupee", "rs.", "rs", "pkr"):
        clean = clean.replace(word, "")
    clean = clean.replace(",", "").replace(" ", "")
    multiplier = 1.0
    for word, factor in (("thousand", 1000.0), ("lakhs", 100000.0), ("lakh", 100000.0),
                         ("lacs", 100000.0), ("lac", 100000.0), ("k", 1000.0)):
        if clean.endswith(word):
            multiplier = factor
            clean = clean[: -len(word)]
            break

    try:
        return float(clean) * multiplier
    except (ValueError, TypeError):
        return None


def _amount_value(match: re.Match, prefix: str = "") -> float | None:
    """
    The rupee value of an `_AMOUNT` match. A bare small number with no currency
    and no multiplier ("under 5") is not taken as a budget — no photographer
    charges Rs 5, and it is far more likely to be a count of something.
    """
    cur = match.group(f"{prefix}cur")
    mul = match.group(f"{prefix}mul")
    value = _parse_price_value(f"{match.group(f'{prefix}num')}{mul or ''}")
    if value is None:
        return None
    if not cur and not mul and value < 1000:
        return None
    return value


def _parse_budget(lower: str) -> tuple[float | None, float | None]:
    """(min_price, max_price) named in the request, or None for each."""
    amount_a = _AMOUNT.replace("?P<", "?P<a_")
    amount_b = _AMOUNT.replace("?P<", "?P<b_")

    # Range: "between 20k and 50k", "20k to 50k", "Rs 20,000 - 50,000"
    range_match = re.search(
        rf"(?:between\s*|from\s*)?{amount_a}\s*(?:and|to|-|–)\s*{amount_b}", lower
    )
    if range_match:
        low = _amount_value(range_match, "a_")
        high = _amount_value(range_match, "b_")
        # "20 to 50k": the multiplier on the second number applies to both
        if low is None and high is not None and not range_match.group("a_mul"):
            raw_low = _parse_price_value(range_match.group("a_num"))
            if raw_low is not None and range_match.group("b_mul"):
                low = _parse_price_value(f"{range_match.group('a_num')}{range_match.group('b_mul')}")
        if low is not None and high is not None and low < high:
            return low, high

    # Ceiling with the keyword before the amount: "under 50k", "budget is Rs 40,000"
    # Every match is tried, so a number that is not money ("for 2 people")
    # earlier in the sentence cannot hide the real budget after it.
    before = re.finditer(
        r"\b(?:under|below|less\s+than|not\s+more\s+than|no\s+more\s+than|at\s+most|"
        r"up\s*to|upto|max(?:imum)?|within|budget(?:\s+(?:of|is|around|under|upto|up\s*to))?|"
        r"around|approx(?:imately)?|for)\s*:?\s*" + _AMOUNT,
        lower,
    )
    for match in before:
        value = _amount_value(match)
        if value is not None:
            return None, value

    # Ceiling with the keyword after: "50k budget", "40,000 max", "50k or less"
    after = re.finditer(
        _AMOUNT + r"\s*(?:budget|max(?:imum)?|or\s+less|or\s+below|or\s+under|only)\b",
        lower,
    )
    for match in after:
        value = _amount_value(match)
        if value is not None:
            return None, value

    # A lone amount with a currency or multiplier: "Rs 50000", "60k"
    amount = re.compile(_AMOUNT)
    for lone in re.finditer(
        rf"(?:\b{_CURRENCY}\s*\d|(?<![\d.,])\d[\d,.]*\s*{_MULTIPLIER}\b)", lower
    ):
        bare = amount.match(lower, lone.start())
        if bare:
            value = _amount_value(bare)
            if value is not None:
                return None, value

    return None, None


def _rule_based_parse(prompt: str) -> ShootConstraints:
    """
    Deterministic zero-latency semantic parser for Pakistani shoot descriptions.
    """
    text = prompt.strip()
    lower = text.lower()

    # 1. City extraction
    matched_city = _find_city(text)

    # 2. Event type and Category
    matched_category = None
    matched_event = None
    for keyword, (cat, evt) in EVENT_CATEGORY_MAP.items():
        if re.search(rf"\b{re.escape(keyword)}(?:s|es)?\b", lower):
            matched_category = cat
            matched_event = evt
            break

    # 3. Budget / Price ceiling & floor
    min_price, max_price = _parse_budget(lower)

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

def _rs(value) -> str:
    return f"Rs. {int(value):,}"


def _explain_no_match(constraints: ShootConstraints) -> str:
    """
    Say WHICH requirement nothing met, and what would work instead. "No
    matches" alone leaves the buyer guessing whether the city, the budget or
    something else was the problem.
    """
    from django.db.models import Max, Min

    from apps.catalog.models import Service
    from apps.profiles import selectors

    city = constraints.city
    where = f" in {city}" if city else ""

    # 1. The city itself — nobody is listed there.
    scope = selectors.visible_photographers()
    if city:
        scope = scope.filter(user__city__iexact=city)
        if not scope.exists():
            return (
                f"No photographers are listed in {city} yet. "
                "Try a nearby city, or leave the city out to search all of Pakistan."
            )

    # 2. The kind of photographer — none of that category there. Other kinds
    #    are never offered instead: they are not what the buyer asked for.
    if constraints.category:
        kind = constraints.category.replace("_", " ")
        scope = scope.filter(categories__slug=constraints.category)
        if not scope.exists():
            return (
                f"No {kind} photographers are listed{where} yet. "
                + ("Try a nearby city." if city else "Please check back soon.")
            )
        where = f"{where} for {kind} shoots"

    # 3. The budget — nothing in the city is priced inside it.
    if constraints.max_price is not None or constraints.min_price is not None:
        prices = Service.objects.filter(
            photographer__in=scope, is_active=True, is_deleted=False
        ).aggregate(low=Min("price"), high=Max("price"))
        low, high = prices["low"], prices["high"]
        if low is not None:
            in_range = Service.objects.filter(
                photographer__in=scope, is_active=True, is_deleted=False
            )
            if constraints.max_price is not None:
                in_range = in_range.filter(price__lte=constraints.max_price)
            if constraints.min_price is not None:
                in_range = in_range.filter(price__gte=constraints.min_price)
            if not in_range.exists():
                if constraints.min_price is not None and constraints.max_price is not None:
                    return (
                        f"Nothing{where} is priced between {_rs(constraints.min_price)} and "
                        f"{_rs(constraints.max_price)}. Prices{where} range from {_rs(low)} "
                        f"to {_rs(high)} — try a budget inside that range."
                    )
                if constraints.max_price is not None:
                    return (
                        f"Nothing{where} fits your budget of {_rs(constraints.max_price)}. "
                        f"The lowest price{where} is {_rs(low)} — try a budget of at least "
                        f"{_rs(low)}."
                    )
                return (
                    f"Nothing{where} costs {_rs(constraints.min_price)} or more. "
                    f"The highest price{where} is {_rs(high)}."
                )

    # 4. The quality filters — rating or verification.
    extras = []
    if constraints.min_rating:
        extras.append(f"rated {constraints.min_rating:g}★ or higher")
    if constraints.verified_only:
        extras.append("verified")
    if extras:
        budget = f" within {_rs(constraints.max_price)}" if constraints.max_price is not None else ""
        return (
            f"No photographers{where}{budget} are {' and '.join(extras)}. "
            "Try removing \"top rated\" or \"verified\" from your request."
        )

    return (
        f"I couldn't find photographers{where} for that combination. "
        "Try a higher budget, or leave out some details."
    )


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
    #
    # City and budget are hard requirements: a buyer who says "in Lahore under
    # 50k" must never be shown a Karachi photographer or one whose cheapest
    # shoot is 80k. They are filters, not just score factors.
    # The event type works the same way: "mehndi" means a wedding photographer,
    # so a corporate or fashion photographer is never a match for it.
    def candidate_queryset():
        queryset = selectors.visible_photographers()

        if constraints.city:
            queryset = queryset.filter(user__city__iexact=constraints.city)

        if constraints.max_price is not None or constraints.min_price is not None:
            in_budget = Service.objects.filter(
                photographer=OuterRef("pk"), is_active=True, is_deleted=False
            )
            if constraints.max_price is not None:
                in_budget = in_budget.filter(price__lte=constraints.max_price)
            if constraints.min_price is not None:
                in_budget = in_budget.filter(price__gte=constraints.min_price)
            queryset = queryset.filter(Exists(in_budget))

        if constraints.category:
            queryset = queryset.filter(categories__slug=constraints.category)

        if constraints.min_rating:
            queryset = queryset.filter(avg_rating__gte=constraints.min_rating)

        if constraints.verified_only:
            queryset = queryset.filter(is_verified=True)

        return queryset

    queryset = candidate_queryset()

    # Prefetch active services and candidate portfolio images
    services_prefetch = Prefetch(
        "services",
        queryset=Service.objects.filter(is_active=True, is_deleted=False)
        .select_related("category").order_by("price"),
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

    # No widening: showing a corporate photographer to someone who asked for a
    # mehndi is a wrong answer, not a broader one. With few or no matches the
    # buyer gets those few, or a message saying what to change.
    relaxed_notice = None

    scored_photographers: list[dict[str, Any]] = []

    for p in candidates:
        services = getattr(p, "curated_services", [])
        images = getattr(p, "curated_images", [])

        # The card shows "from Rs {base_price}". The stored column can be out
        # of date (seeded data was never reconciled with the services), which
        # made an in-budget photographer look over budget. Show the real
        # cheapest active service instead; nothing is saved.
        if services:
            p.base_price = services[0].price

        # ─── Factor A: Budget Compatibility (Weight: 30%) ─────────────────────
        budget_score = 1.0
        best_service = None

        if constraints.max_price:
            matching_services = [
                s for s in services
                if float(s.price) <= constraints.max_price
                and (constraints.min_price is None or float(s.price) >= constraints.min_price)
            ]
            if matching_services:
                # Quote a service of the kind asked for when one fits the
                # budget, so a wedding request is not answered with the price
                # of a birthday package.
                same_kind = [
                    s for s in matching_services
                    if constraints.category and s.category.slug == constraints.category
                ]
                best_service = (same_kind or matching_services)[0]
                budget_score = 1.0
            elif float(p.base_price) <= constraints.max_price:
                budget_score = 0.95
            else:
                # Penalize gracefully based on price overshoot
                excess_ratio = (float(p.base_price) - constraints.max_price) / max(1.0, constraints.max_price)
                budget_score = max(0.2, 1.0 - excess_ratio)
        else:
            same_kind = [
                s for s in services
                if constraints.category and s.category.slug == constraints.category
            ]
            best_service = (same_kind or services)[0] if services else None

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
        assistant_message = _explain_no_match(constraints)

    return {
        "assistant_message": assistant_message,
        "parsed_filters": constraints.to_dict(),
        "suggested_chips": constraints.suggested_chips,
        "relaxed_notice": relaxed_notice,
        "total_matches": len(scored_photographers),
        "photographers": [m["photographer"] for m in top_matches],
    }
