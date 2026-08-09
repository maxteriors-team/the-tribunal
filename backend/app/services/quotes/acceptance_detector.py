"""Detect when an inbound text is the customer accepting an outstanding quote.

A "yes" to a proposal is not a booking signal, but the text agent had no way to
tell the difference. Its prompt is a booking funnel with no quote awareness at
all, so "this is approved, thanks so much!" read as buying intent and the agent
did the only thing it knows how to do: offer two slots and book a discovery call
for a job the customer had *already bought*.

Detection is two-stage, mirroring the opt-out detector: a cheap keyword
pre-filter so the common case costs nothing, then an LLM classifier to separate
a real acceptance from the phrasings that merely look like one ("approved" in
"has your quote been approved yet?", or a question about the proposal).

Both stages are deliberately conservative. A false positive parks a live
conversation on a human, which is recoverable and even desirable. A false
negative just leaves today's behaviour in place.
"""

from __future__ import annotations

import asyncio
import re
import uuid

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quote import Quote
from app.services.ai.openai_credentials import (
    OpenAICredentialContext,
    build_async_openai_client,
    get_openai_bearer_token,
)

logger = structlog.get_logger()

__all__ = [
    "classify_quote_acceptance",
    "find_outstanding_quote",
    "has_potential_acceptance_keywords",
]


# Phrases that could mean "I accept the proposal". Broad on purpose — the
# classifier is what makes the decision, this only decides whether to ask it.
ACCEPTANCE_KEYWORDS = (
    "approved",
    "approve",
    "accepted",
    "accept",
    "signed",
    "sign",
    "looks good",
    "sounds good",
    "lets do it",
    "let's do it",
    "lets go",
    "do it",
    "were good to go",
    "good to go",
    "go ahead",
    "move forward",
    "moving forward",
    "proceed",
    "im in",
    "i'm in",
    "count me in",
    "book it",
    "send the invoice",
    "send invoice",
    "how do i pay",
    "deposit",
    "yes",
    "yep",
    "yeah",
    "confirmed",
)

ACCEPTANCE_CLASSIFIER_PROMPT = """You are a message intent classifier for a home-services CRM.

The customer has an outstanding written proposal/quote for work at their property.
Decide whether their latest message is them ACCEPTING that proposal — agreeing to
buy the work.

TRUE (accepting the proposal):
- "This is approved, thanks so much!"
- "Looks good, let's do it"
- "We're good to go, send the invoice"
- "Approved. When can you start?"
- "Yes, go ahead with the quote"
- "Signed and sent back"
- "Where do I send the deposit?"

FALSE (not accepting the proposal):
- "Yes, that's my email" (answering a different question)
- "Yes I got it" / "Yes I saw the quote" (acknowledging receipt only)
- "Looks good but can we drop the gutter line?" (negotiating, not accepting)
- "Has this been approved on your end?" (asking a question)
- "Sounds good, what days are you free?" (agreeing to talk, not buying)
- "Yes" replying to "can I ask you a question?"
- "Not approved" / "we decided against it" (declining)

Ambiguity rule: if the message could plausibly be answering the agent's previous
question rather than accepting the proposal, answer false.

Respond with ONLY "true" or "false" - no other text."""


async def find_outstanding_quote(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int | None,
) -> Quote | None:
    """Return this contact's most recent quote still awaiting a decision.

    Only ``sent`` quotes qualify. A ``draft`` was never shown to the customer, and
    ``approved``/``declined``/``expired`` already have their answer — re-running
    the intercept on those would re-page a human every time the customer texts.
    """
    if contact_id is None:
        return None

    result = await db.execute(
        select(Quote)
        .where(
            Quote.workspace_id == workspace_id,
            Quote.contact_id == contact_id,
            Quote.status == "sent",
        )
        .order_by(Quote.sent_at.desc().nulls_last(), Quote.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def has_potential_acceptance_keywords(message: str) -> bool:
    """Fast pre-filter: could this message plausibly be an acceptance?"""
    if not message:
        return False
    normalized = re.sub(r"[^\w\s']", " ", message.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    padded = f" {normalized} "
    return any(f" {keyword} " in padded for keyword in ACCEPTANCE_KEYWORDS)


async def classify_quote_acceptance(
    message: str,
    conversation_context: list[dict[str, str]] | None = None,
    *,
    credential: OpenAICredentialContext | None = None,
    openai_api_key: str | None = None,
) -> bool:
    """Return whether *message* accepts the customer's outstanding proposal.

    Returns ``False`` on every failure path — no key, timeout, API error. The
    fallback has to be "keep today's behaviour" rather than a keyword guess:
    silently parking a conversation on a human because a classifier timed out is
    worse than the bug this guards against.
    """
    log = logger.bind(message_preview=message[:50] if message else "")

    api_key = (
        credential.bearer_token if credential is not None else openai_api_key
    ) or get_openai_bearer_token()
    if not api_key:
        log.warning("no_openai_key_for_acceptance_classifier")
        return False

    context_text = ""
    if conversation_context:
        recent = conversation_context[-4:]
        context_lines = [
            f"{'Customer' if msg.get('role') == 'user' else 'Agent'}: {msg.get('content', '')}"
            for msg in recent
        ]
        context_text = "Recent conversation:\n" + "\n".join(context_lines) + "\n\n"

    user_message = (
        f'{context_text}Message to classify: "{message}"\n\n'
        "Is the customer accepting the outstanding proposal?"
    )

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
                    {"role": "system", "content": ACCEPTANCE_CLASSIFIER_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,
                max_completion_tokens=10,
            ),
            timeout=5.0,
        )
        result_text = response.choices[0].message.content or ""
        accepted = result_text.strip().lower() == "true"
        log.info("quote_acceptance_classified", result=accepted, raw=result_text.strip())
        return accepted
    except TimeoutError:
        log.warning("quote_acceptance_classifier_timeout")
        return False
    except Exception as exc:  # noqa: BLE001 - never break the nurture path
        log.warning("quote_acceptance_classifier_error", error=str(exc))
        return False
