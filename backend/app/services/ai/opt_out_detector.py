"""AI-powered opt-out detection for SMS/text conversations.

This module provides intelligent opt-out detection that distinguishes between
genuine opt-out requests ("stop texting me") and false positives like
"I think you should quit" (telling someone to give up).

Uses GPT-4o-mini for semantic classification when keywords are detected,
falling back to simple keyword matching when API is unavailable.

Usage:
    from app.services.ai.opt_out_detector import (
        has_potential_opt_out_keywords,
        classify_opt_out_intent,
    )

    # Fast pre-filter
    if has_potential_opt_out_keywords(message):
        # Run AI classifier for confirmation
        is_opt_out = await classify_opt_out_intent(message, context)
"""

import asyncio
import re

import structlog
from openai import AsyncOpenAI

from app.services.ai.openai_credentials import (
    OpenAICredentialContext,
    build_async_openai_client,
    get_openai_bearer_token,
)

logger = structlog.get_logger()

# Opt-out keywords that trigger AI classification
# These are potential opt-out signals that need context verification
OPT_OUT_KEYWORDS = [
    "stop",
    "stopall",
    "unsubscribe",
    "opt out",
    "optout",
    "cancel",
    "end",
    "quit",
    "remove",
    "unsub",
    # Additional phrases for edge cases
    "take me off",
    "don't want",
    "dont want",
    "no more messages",
    "stop messaging",
    "stop texting",
    "leave me alone",
]

# Simple opt-outs that don't need AI verification
SIMPLE_OPT_OUTS = ["stop", "stopall", "unsubscribe", "opt out", "optout"]

# System prompt for opt-out classification
OPT_OUT_CLASSIFIER_PROMPT = """You are a message intent classifier. Determine if the user \
is requesting to opt out of receiving messages (SMS/text communications).

TRUE OPT-OUT examples (user wants to stop receiving messages):
- "STOP"
- "Stop texting me"
- "Unsubscribe"
- "Remove me from this list"
- "I don't want these messages anymore"
- "Quit sending me texts"
- "Please stop contacting me"

FALSE OPT-OUT examples (NOT requesting to stop messages):
- "I think you should quit" (telling someone to quit their job/give up)
- "Don't quit on me" (encouragement)
- "I quit my job last week" (unrelated statement)
- "Stop wasting my time with bad offers" (complaint, but still engaged)
- "This is the end of our conversation" (ending chat, not unsubscribing)
- "Cancel my appointment" (canceling something else, not messages)
- "Remove my name from the appointment" (editing, not unsubscribing)

Respond with ONLY "true" or "false" - no other text."""


def has_potential_opt_out_keywords(message: str) -> bool:
    """Check if message contains potential opt-out keywords.

    This is a fast pre-filter before running the AI classifier.

    Args:
        message: The message text to check

    Returns:
        True if message contains any opt-out keywords
    """
    message_normalized = re.sub(r"[^\w\s]", "", message.lower().strip())
    return any(keyword in message_normalized for keyword in OPT_OUT_KEYWORDS)


async def classify_opt_out_intent(
    message: str,
    conversation_context: list[dict[str, str]] | None = None,
    openai_api_key: str | None = None,
    *,
    credential: OpenAICredentialContext | None = None,
) -> bool:
    """Use AI to determine if a message is a genuine opt-out request.

    This function uses GPT-5.4-nano to understand the semantic intent
    of a message, distinguishing between actual opt-out requests and
    messages that happen to contain opt-out keywords in other contexts.

    Args:
        message: The message to classify
        conversation_context: Optional recent conversation history for context
        openai_api_key: OpenAI API key (uses settings if not provided)

    Returns:
        True if the message is a genuine opt-out request, False otherwise
    """
    log = logger.bind(message_preview=message[:50] if message else "")

    api_key = (credential.bearer_token if credential is not None else openai_api_key) or (
        get_openai_bearer_token()
    )
    if not api_key:
        log.warning("no_openai_key_for_opt_out_classifier")
        # Fall back to keyword-only detection if no API key
        return has_potential_opt_out_keywords(message)

    # Build the user message with context if available
    context_text = ""
    if conversation_context and len(conversation_context) > 0:
        # Include last 3 messages for context
        recent = conversation_context[-3:]
        context_lines = []
        for msg in recent:
            role = "Customer" if msg["role"] == "user" else "Agent"
            context_lines.append(f"{role}: {msg['content']}")
        context_text = "Recent conversation:\n" + "\n".join(context_lines) + "\n\n"

    user_message = f"""{context_text}Message to classify: "{message}"

Is this a genuine opt-out request (user wants to stop receiving SMS/text messages)?"""

    client = (
        build_async_openai_client(credential)
        if credential is not None
        else AsyncOpenAI(api_key=api_key)
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-5.4-nano",
                messages=[
                    {"role": "system", "content": OPT_OUT_CLASSIFIER_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,  # Deterministic for classification
                max_completion_tokens=10,  # Only need "true" or "false"
            ),
            timeout=5.0,  # Fast timeout for classification
        )

        result_text = response.choices[0].message.content or ""
        is_opt_out = result_text.strip().lower() == "true"

        log.info(
            "opt_out_classified",
            result=is_opt_out,
            raw_response=result_text.strip(),
        )

        return is_opt_out

    except TimeoutError:
        log.warning("opt_out_classifier_timeout")
        # On timeout, be conservative and check keywords only
        # If message is just "STOP" or "unsubscribe", treat as opt-out
        return message.lower().strip() in SIMPLE_OPT_OUTS

    except Exception as e:
        log.exception("opt_out_classifier_error", error=str(e))
        # On error, fall back to simple keyword check for obvious opt-outs
        return message.lower().strip() in SIMPLE_OPT_OUTS
