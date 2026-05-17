"""Classify inbound SMS replies for drip campaign response handling.

Two-layer approach:
1. Fast keyword matching (no API cost, handles clear signals)
2. LLM fallback for ambiguous replies

Each classification maps to an action:
- interested / hand_raiser → pause drip, AI agent takes over
- not_interested / opt_out → cancel drip
- timing → pause drip, re-enroll in long-term nurture later
- question → pause drip, AI agent responds
- appointment_request → pause drip, AI agent books appointment
- unknown → pause drip, AI agent handles
"""

import asyncio

import structlog
from openai import AsyncOpenAI

from app.models.drip_campaign import ResponseCategory

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Keyword rules (checked first — fast, free, deterministic)
# ---------------------------------------------------------------------------

_KEYWORD_RULES: dict[ResponseCategory, list[str]] = {
    ResponseCategory.OPT_OUT: [
        "stop",
        "unsubscribe",
        "opt out",
        "optout",
        "remove me",
        "take me off",
        "don't text",
        "dont text",
        "don't contact",
        "dont contact",
        "leave me alone",
        "wrong number",
        "wrong person",
        "spam",
        "reported",
        "do not contact",
    ],
    ResponseCategory.NOT_INTERESTED: [
        "not interested",
        "no thanks",
        "no thank you",
        "no thx",
        "not looking",
        "pass",
        "nope",
        "not right now",
        "don't need",
        "dont need",
        "already sold",
        "already have an agent",
        "already working with",
        "go away",
    ],
    ResponseCategory.APPOINTMENT_REQUEST: [
        "book",
        "schedule",
        "set up a call",
        "set up a meeting",
        "let's meet",
        "lets meet",
        "when are you free",
        "what times",
        "available",
        "appointment",
        "i'd like to meet",
        "can we talk",
        "call me",
    ],
    ResponseCategory.INTERESTED: [
        "yes",
        "yeah",
        "yep",
        "sure",
        "send it",
        "send me",
        "i'd love",
        "id love",
        "i'd like",
        "id like",
        "sounds good",
        "sounds great",
        "interested",
        "tell me more",
        "more info",
        "please do",
        "that would be great",
        "love to",
        "absolutely",
        "yes please",
        "for sure",
    ],
    ResponseCategory.TIMING: [
        "not now",
        "maybe later",
        "next year",
        "in a few months",
        "not yet",
        "down the road",
        "later",
        "not ready yet",
        "check back",
        "reach out later",
        "after the holidays",
    ],
    ResponseCategory.QUESTION: [
        "how much",
        "what's my home worth",
        "what would",
        "how does",
        "what do you",
        "can you explain",
        "what's the market",
        "whats the market",
        "how long",
        "what area",
        "which neighborhood",
    ],
}


def classify_by_keywords(message: str) -> ResponseCategory | None:
    """Classify a message using keyword matching. Returns None if ambiguous."""
    text = message.lower().strip()

    # Check opt-out first (highest priority)
    for keyword in _KEYWORD_RULES[ResponseCategory.OPT_OUT]:
        if keyword in text:
            return ResponseCategory.OPT_OUT

    # Short affirmative replies are almost always "interested"
    if text in {"yes", "yeah", "yep", "sure", "ok", "okay", "y", "yea"}:
        return ResponseCategory.INTERESTED

    # Check remaining categories
    scores: dict[ResponseCategory, int] = {}
    for category, keywords in _KEYWORD_RULES.items():
        if category == ResponseCategory.OPT_OUT:
            continue
        matches = sum(1 for kw in keywords if kw in text)
        if matches > 0:
            scores[category] = matches

    if not scores:
        return None

    # Return the highest-scoring category
    best = max(scores, key=lambda k: scores[k])
    return best


# ---------------------------------------------------------------------------
# LLM fallback for ambiguous replies
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a response classifier for a real estate lead "
    "reactivation SMS campaign.\n\n"
    "Classify the contact's reply into exactly ONE of "
    "these categories:\n"
    "- interested: Want to learn more or engage\n"
    "- not_interested: Don't want to be contacted\n"
    "- timing: Interested but not right now\n"
    "- question: Asking about real estate or the offer\n"
    "- appointment_request: Want to schedule a call/meeting\n"
    "- opt_out: Want to stop receiving messages\n"
    "- unknown: Cannot determine intent\n\n"
    "Respond with ONLY the category name, nothing else."
)


async def classify_by_llm(
    message: str,
    conversation_context: list[dict[str, str]] | None,
    openai_api_key: str,
) -> ResponseCategory:
    """Classify a message using LLM when keyword matching is ambiguous."""
    client = AsyncOpenAI(api_key=openai_api_key)

    user_content = f'Contact\'s reply: "{message}"'
    if conversation_context:
        recent = conversation_context[-4:]
        context_str = "\n".join(
            f"{'Agent' if m['role'] == 'assistant' else 'Contact'}: {m['content']}" for m in recent
        )
        user_content = (
            f'Recent conversation:\n{context_str}\n\nContact\'s latest reply: "{message}"'
        )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-5.4-nano",
                messages=[
                    {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                max_completion_tokens=20,
            ),
            timeout=10.0,
        )

        result = (response.choices[0].message.content or "").strip().lower()

        # Map to enum
        category_map: dict[str, ResponseCategory] = {
            "interested": ResponseCategory.INTERESTED,
            "not_interested": ResponseCategory.NOT_INTERESTED,
            "timing": ResponseCategory.TIMING,
            "question": ResponseCategory.QUESTION,
            "appointment_request": ResponseCategory.APPOINTMENT_REQUEST,
            "opt_out": ResponseCategory.OPT_OUT,
            "unknown": ResponseCategory.UNKNOWN,
        }
        return category_map.get(result, ResponseCategory.UNKNOWN)

    except Exception:
        logger.exception("llm_classification_failed")
        return ResponseCategory.UNKNOWN


async def classify_response(
    message: str,
    conversation_context: list[dict[str, str]] | None = None,
    openai_api_key: str | None = None,
) -> ResponseCategory:
    """Classify an inbound SMS reply. Keyword-first, LLM-fallback.

    Args:
        message: The inbound SMS text
        conversation_context: Optional recent messages for LLM context
        openai_api_key: Required for LLM fallback

    Returns:
        The classified ResponseCategory
    """
    # Layer 1: keyword matching
    keyword_result = classify_by_keywords(message)
    if keyword_result is not None:
        logger.info(
            "response_classified_by_keywords",
            category=keyword_result.value,
            message_preview=message[:50],
        )
        return keyword_result

    # Layer 2: LLM fallback
    if openai_api_key:
        llm_result = await classify_by_llm(message, conversation_context, openai_api_key)
        logger.info(
            "response_classified_by_llm",
            category=llm_result.value,
            message_preview=message[:50],
        )
        return llm_result

    # No LLM key — default to unknown (will pause drip, AI takes over)
    return ResponseCategory.UNKNOWN
