"""
Dynamic Smart Reply Suggestions for Chat.

Generates contextual quick-reply chips for photographers (and buyers) based on:
1. Buyer's last message intent (Availability, Pricing/Packages, Delivery, Location, Portfolio, Greeting).
2. The photographer's real-time calendar availability (e.g., checking Dec 14).
3. The photographer's real active services and package pricing.
4. The photographer's turnaround time and deliverables.

Tapping a quick-reply chip lets photographers reply in a single tap,
keeping avg_response_time_hours near instant.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger("snapsphere")

MONTH_NAMES = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _extract_target_date(text: str) -> tuple[date | None, str | None]:
    """
    Extract date mentioned in message (e.g., 'Dec 14', '14th December', '2026-12-14').
    Returns (resolved_date, formatted_label).
    """
    clean = text.lower()
    today = timezone.now().date()
    current_year = today.year

    # 1. Pattern: Month Day (e.g. 'Dec 14', 'December 14th')
    m1 = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*([0-9]{1,2})(?:st|nd|rd|th)?\b",
        clean,
    )
    if m1:
        month_str, day_str = m1.group(1), m1.group(2)
        month = MONTH_NAMES.get(month_str, 1)
        day = int(day_str)
        try:
            target_year = current_year if (month >= today.month or (month == today.month and day >= today.day)) else current_year + 1
            d = date(target_year, month, day)
            label = d.strftime("%b %d")
            return d, label
        except ValueError:
            pass

    # 2. Pattern: Day Month (e.g. '14th Dec', '14 December')
    m2 = re.search(
        r"\b([0-9]{1,2})(?:st|nd|rd|th)?\s*(?:of\s*)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
        clean,
    )
    if m2:
        day_str, month_str = m2.group(1), m2.group(2)
        month = MONTH_NAMES.get(month_str, 1)
        day = int(day_str)
        try:
            target_year = current_year if (month >= today.month or (month == today.month and day >= today.day)) else current_year + 1
            d = date(target_year, month, day)
            label = d.strftime("%b %d")
            return d, label
        except ValueError:
            pass

    # 3. Pattern: YYYY-MM-DD
    m3 = re.search(r"\b(202[0-9])-(0?[1-9]|1[0-2])-(0?[1-9]|[12][0-9]|3[01])\b", clean)
    if m3:
        try:
            d = date(int(m3.group(1)), int(m3.group(2)), int(m3.group(3)))
            return d, d.strftime("%b %d")
        except ValueError:
            pass

    # 4. Pattern: relative days (e.g. 'tomorrow', 'this weekend', 'saturday')
    if "tomorrow" in clean:
        d = today + timedelta(days=1)
        return d, "tomorrow"
    if "this weekend" in clean or "next weekend" in clean:
        days_ahead = 5 - today.weekday() if today.weekday() < 5 else 6 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        d = today + timedelta(days=days_ahead)
        return d, "this weekend"

    return None, None


def generate_smart_replies(conversation, for_user, limit: int = 4) -> list[dict[str, Any]]:
    """
    Generate dynamic smart-reply suggestions for the conversation.
    """
    from apps.chat.models import Message
    from apps.catalog.models import Service

    # Fetch last message in the thread
    last_msg = (
        Message.objects.filter(conversation=conversation, is_deleted=False)
        .order_by("-created_at")
        .first()
    )

    # Determine role
    photographer = getattr(for_user, "photographer_profile", None)
    is_photographer = photographer is not None

    replies: list[dict[str, Any]] = []

    # If no message yet (freshly started conversation)
    if not last_msg:
        if is_photographer:
            starting_pkr = int(photographer.base_price) if photographer.base_price else 25000
            replies.extend([
                {
                    "text": "Hello! Thanks for reaching out. What event date and city are you planning for?",
                    "category": "greeting",
                    "confidence": 0.95,
                },
                {
                    "text": f"Hi there! My packages start from Rs. {starting_pkr:,}. Feel free to share your shoot details!",
                    "category": "pricing",
                    "confidence": 0.90,
                },
                {
                    "text": "Salam! I'd love to help capture your special event. Are you looking for wedding or portrait coverage?",
                    "category": "greeting",
                    "confidence": 0.88,
                },
            ])
        else:
            replies.extend([
                {
                    "text": "Hi! Are you available for an upcoming shoot?",
                    "category": "inquiry",
                    "confidence": 0.95,
                },
                {
                    "text": "Can you please share your packages and pricing details?",
                    "category": "pricing",
                    "confidence": 0.90,
                },
                {
                    "text": "What is included in your full-day event package?",
                    "category": "deliverables",
                    "confidence": 0.85,
                },
            ])
        return replies[:limit]

    # If the last message was sent by the caller themselves, they are waiting for response
    if last_msg.sender_id == for_user.id:
        if is_photographer:
            replies.append({
                "text": "Let me know if you have any other questions regarding packages or dates!",
                "category": "followup",
                "confidence": 0.85,
            })
            replies.append({
                "text": "I can also share my customized package invoice if you'd like to proceed.",
                "category": "pricing",
                "confidence": 0.80,
            })
        else:
            replies.append({
                "text": "Looking forward to hearing from you!",
                "category": "followup",
                "confidence": 0.85,
            })
        return replies[:limit]

    # The caller is responding to an incoming message from the other party
    incoming_text = last_msg.body.strip()
    incoming_lower = incoming_text.lower()

    if is_photographer:
        # ─── 1. AVAILABILITY INTENT ──────────────────────────────────────────
        target_date, date_label = _extract_target_date(incoming_text)
        is_avail_inquiry = bool(
            target_date
            or re.search(r"\b(available|free|open|slot|schedule|dates?|timing)\b", incoming_lower)
        )

        if is_avail_inquiry:
            if target_date:
                # Query actual calendar availability
                is_available = True
                try:
                    from apps.availability.selectors import day_availability
                    status = day_availability(photographer, target_date)
                    is_available = getattr(status, "is_available", True)
                except Exception as exc:
                    logger.debug("Smart reply availability check: %s", exc)

                display_date = date_label or target_date.strftime("%b %d")
                if is_available:
                    replies.append({
                        "text": f"Yes, I am available on {display_date}! Would you like to proceed with the booking?",
                        "category": "availability",
                        "confidence": 0.98,
                    })
                    replies.append({
                        "text": f"I have that slot open on {display_date}. Let's lock in your date before it gets booked!",
                        "category": "availability",
                        "confidence": 0.92,
                    })
                else:
                    alt_date = (target_date + timedelta(days=1)).strftime("%b %d")
                    replies.append({
                        "text": f"I am booked on {display_date}, but {alt_date} is currently available if that works for you!",
                        "category": "availability",
                        "confidence": 0.95,
                    })
                    replies.append({
                        "text": f"Unfortunately {display_date} is already reserved, but feel free to check other dates on my profile.",
                        "category": "availability",
                        "confidence": 0.88,
                    })
            else:
                replies.append({
                    "text": "Yes, I am available! What event date and timings are you looking for?",
                    "category": "availability",
                    "confidence": 0.94,
                })
                replies.append({
                    "text": "I am currently accepting bookings this month. Which date do you have in mind?",
                    "category": "availability",
                    "confidence": 0.90,
                })

        # ─── 2. PRICING & PACKAGES INTENT ────────────────────────────────────
        is_price_inquiry = bool(
            re.search(r"\b(price|pricing|package|packages|rate|rates|cost|budget|charges|quote|how much|discount|deal)\b", incoming_lower)
        )

        active_services = list(
            Service.objects.filter(photographer=photographer, is_active=True, is_deleted=False).order_by("price")
        )
        top_service = active_services[0] if active_services else None
        base_price_int = int(photographer.base_price) if photographer.base_price else 25000

        if is_price_inquiry:
            if top_service:
                replies.append({
                    "text": f"Here is my customized package: '{top_service.title}' for Rs. {int(top_service.price):,}.",
                    "category": "pricing",
                    "confidence": 0.96,
                })
            replies.append({
                "text": f"My packages start from Rs. {base_price_int:,}. I can also tailor a customized package for your exact event needs!",
                "category": "pricing",
                "confidence": 0.92,
            })
            replies.append({
                "text": "I'd be glad to customize a package within your budget. How many hours of coverage will you need?",
                "category": "pricing",
                "confidence": 0.88,
            })

        # ─── 3. DELIVERY & TURNAROUND INTENT ─────────────────────────────────
        is_delivery_inquiry = bool(
            re.search(r"\b(deliver|delivery|turnaround|when will|how long|editing|photos ready|sneak peek|gallery)\b", incoming_lower)
        )
        if is_delivery_inquiry:
            days = min([s.delivery_days for s in active_services if s.delivery_days > 0] or [7])
            replies.append({
                "text": f"I deliver edited high-res photos within {days} days, with sneak peeks in 48 hours.",
                "category": "delivery",
                "confidence": 0.95,
            })
            replies.append({
                "text": "Yes, expedited rush delivery is available if you need the photos sooner!",
                "category": "delivery",
                "confidence": 0.89,
            })

        # ─── 4. LOCATION & TRAVEL INTENT ─────────────────────────────────────
        is_location_inquiry = bool(
            re.search(r"\b(location|city|travel|lahore|karachi|islamabad|rawalpindi|venue|outstation|destination)\b", incoming_lower)
        )
        if is_location_inquiry:
            photog_city = photographer.user.city or "the city"
            replies.append({
                "text": f"Yes, I provide full coverage across {photog_city} and travel across Pakistan for events!",
                "category": "location",
                "confidence": 0.93,
            })
            replies.append({
                "text": "Yes, travel is available! We can coordinate venue and logistics once the booking is initiated.",
                "category": "location",
                "confidence": 0.87,
            })

        # ─── 5. PORTFOLIO & SAMPLE INTENT ────────────────────────────────────
        is_portfolio_inquiry = bool(
            re.search(r"\b(portfolio|sample|samples|photos|pictures|work|instagram|shots)\b", incoming_lower)
        )
        if is_portfolio_inquiry:
            replies.append({
                "text": "You can view my verified portfolio and recent albums right here on my profile tab!",
                "category": "portfolio",
                "confidence": 0.94,
            })

        # ─── 6. CONFIRMATION & BOOKING INTENT ────────────────────────────────
        is_confirm_inquiry = bool(
            re.search(r"\b(book|confirm|advance|deposit|lock|proceed|deal|ready)\b", incoming_lower)
        )
        if is_confirm_inquiry:
            replies.append({
                "text": "Great! You can send an official booking request directly through my profile to secure your date.",
                "category": "booking",
                "confidence": 0.96,
            })
            replies.append({
                "text": "Perfect! Please submit the booking request on SnapSphere with the 30% advance deposit to confirm.",
                "category": "booking",
                "confidence": 0.91,
            })

        # ─── 7. GREETING INTENT ──────────────────────────────────────────────
        is_greeting = bool(
            re.search(r"\b(salam|hi|hello|hey|aoa|assalam|good morning|good afternoon)\b", incoming_lower)
        )
        if is_greeting and len(incoming_lower.split()) <= 4:
            replies.append({
                "text": "Wa Alaikum Assalam! Thanks for reaching out. What date and event are you planning for?",
                "category": "greeting",
                "confidence": 0.96,
            })
            replies.append({
                "text": "Hello! I'd love to capture your special day. Feel free to share your event details!",
                "category": "greeting",
                "confidence": 0.92,
            })

        # ─── 8. FALLBACK / GENERAL QUICK-REPLIES ─────────────────────────────
        if len(replies) < limit:
            fallback_options = [
                {
                    "text": "Here is my customized package. Let me know if that works for you!",
                    "category": "pricing",
                    "confidence": 0.80,
                },
                {
                    "text": "Thanks for your message! Could you confirm your event date and venue location?",
                    "category": "general",
                    "confidence": 0.78,
                },
                {
                    "text": "I can definitely accommodate that. Feel free to send a booking request to lock the date!",
                    "category": "booking",
                    "confidence": 0.75,
                },
            ]
            for fb in fallback_options:
                if not any(r["text"] == fb["text"] for r in replies):
                    replies.append(fb)

    else:
        # Buyer smart replies (when buyer is chatting with photographer)
        replies.extend([
            {
                "text": "Are you available on my event date?",
                "category": "availability",
                "confidence": 0.92,
            },
            {
                "text": "Can you share what is included in your customized package?",
                "category": "pricing",
                "confidence": 0.88,
            },
            {
                "text": "How many edited photos are delivered, and what is the turnaround time?",
                "category": "deliverables",
                "confidence": 0.85,
            },
            {
                "text": "Sounds good! I am ready to proceed with booking.",
                "category": "confirmation",
                "confidence": 0.82,
            },
        ])

    # Deduplicate and sort by confidence
    seen = set()
    unique_replies = []
    for r in replies:
        if r["text"] not in seen:
            seen.add(r["text"])
            unique_replies.append(r)

    unique_replies.sort(key=lambda x: x.get("confidence", 0.5), reverse=True)
    return unique_replies[:limit]
