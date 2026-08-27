"""What happens when a customer accepts a proposal over text.

The rule this encodes: **accepting a quote is not a booking event.** The work is
already sold, so there is nothing left to qualify and no discovery call to run.
What the customer actually needs next is an install window, and that window
depends on whether the materials for their job are on hand — a fact the AI has no
reliable view of and must not guess at over SMS.

So the AI stops here. It sends one deterministic acknowledgement that promises a
scheduling call *without naming a time*, parks itself so it cannot keep selling
into a closed deal, and pages a human with the parts list for the job. The human
confirms the approval in the dashboard (which is what orders parts and provisions
the plan) and picks the install week.

Every step is independently guarded. A failed text must still pause the AI, and a
failed notification must still leave the conversation parked — the one outcome
worse than a missing notification is an agent that keeps negotiating a job the
customer already bought.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.quote import Quote
from app.services.notifications import notify_workspace_event
from app.services.telephony.text_provider import (
    get_text_message_provider,
    provider_for_conversation,
)

logger = structlog.get_logger()

__all__ = ["ACKNOWLEDGEMENT_TEMPLATE", "build_acknowledgement", "hand_off_accepted_quote"]


# No date, no time, no slot options. Naming a day here would recreate the exact
# bug this module exists to prevent, just with friendlier wording — the install
# week is not knowable until someone confirms the materials are in.
ACKNOWLEDGEMENT_TEMPLATE = (
    "That's great news, {first_name} — thank you! I've passed your approval to "
    "the team. We'll confirm your install window as soon as your materials are "
    "in, and someone will reach out to lock in a day that works for you. "
    "Nothing else needed from you right now."
)


def build_acknowledgement(contact: Contact) -> str:
    """Render the holding reply sent the moment a proposal is accepted."""
    return ACKNOWLEDGEMENT_TEMPLATE.format(first_name=contact.first_name or "there")


def summarize_materials(quote: Quote) -> dict[str, str]:
    """Return the job's parts list as ``{sku: description}`` for the operator page.

    Sourced from the same ``proposal_document.fulfillment`` bill-of-materials the
    approval flow emails to the workspace, so the human deciding the install week
    sees what has to be in stock before they can promise one.
    """
    document = quote.proposal_document or {}
    raw_parts = document.get("fulfillment") or []
    details: dict[str, str] = {}
    for part in raw_parts:
        if not isinstance(part, dict):
            continue
        sku = str(part.get("sku") or "").strip()
        if not sku:
            continue
        qty = part.get("qty", 0)
        description = str(part.get("description") or "").strip()
        details[sku] = f"Qty {qty}" + (f" — {description}" if description else "")
    return details


async def hand_off_accepted_quote(
    db: AsyncSession,
    *,
    conversation: Conversation,
    contact: Contact,
    quote: Quote,
    agent_id: uuid.UUID | None,
    log: Any = None,
) -> None:
    """Acknowledge the acceptance, park the AI, and page a human.

    Ordering matters: the acknowledgement goes out *before* the pause, because
    the sender re-reads ``ai_paused`` and would suppress its own message.
    """
    log = (log or logger).bind(
        conversation_id=str(conversation.id),
        quote_id=str(quote.id),
        contact_id=contact.id,
    )

    await _send_acknowledgement(
        db,
        conversation=conversation,
        contact=contact,
        agent_id=agent_id,
        log=log,
    )

    # The handoff itself. This is the part that must survive every other failure:
    # an un-paused agent goes back to booking discovery calls on the next inbound.
    conversation.ai_paused = True
    conversation.ai_paused_until = None
    await db.commit()
    log.info("quote_acceptance_ai_paused")

    await _notify_operators(db, conversation=conversation, contact=contact, quote=quote, log=log)


async def _send_acknowledgement(
    db: AsyncSession,
    *,
    conversation: Conversation,
    contact: Contact,
    agent_id: uuid.UUID | None,
    log: Any,
) -> None:
    """Text the customer that their approval landed. Best-effort."""
    if getattr(conversation, "source_provider", None) == "quo":
        log.info("quo_manual_messaging_only")
        return
    body = build_acknowledgement(contact)
    sms_service = get_text_message_provider(provider_for_conversation(conversation))
    try:
        await sms_service.send_message(
            to_number=conversation.contact_phone,
            from_number=conversation.workspace_phone,
            body=body,
            db=db,
            workspace_id=conversation.workspace_id,
            agent_id=agent_id,
        )
        log.info("quote_acceptance_acknowledged")
    except Exception as exc:  # noqa: BLE001 - the pause below matters more
        log.warning("quote_acceptance_acknowledgement_failed", error=str(exc))
    finally:
        await sms_service.close()


async def _notify_operators(
    db: AsyncSession,
    *,
    conversation: Conversation,
    contact: Contact,
    quote: Quote,
    log: Any,
) -> None:
    """Page the workspace: a job just sold and needs an install window."""
    who = contact.full_name or contact.first_name or "A customer"
    body = (
        f"{who} accepted {quote.number} over text. The AI has been paused on this "
        f"conversation. Confirm the approval, then schedule their install once "
        f"materials are in."
    )
    details = summarize_materials(quote)
    try:
        await notify_workspace_event(
            db,
            workspace_id=conversation.workspace_id,
            notification_type="quote_accepted",
            title=f"Quote accepted — {quote.number}",
            body=body,
            data={
                "type": "quote_accepted_via_text",
                "quoteId": str(quote.id),
                "conversationId": str(conversation.id),
                "screen": f"/(tabs)/messages/{conversation.id}",
            },
            channel_id="messages",
            email_subject=f"Quote accepted — {quote.number}",
            email_heading="Schedule this install",
            email_intro=body,
            email_details=details or None,
            # Per quote, not per message: a customer who texts "approved!" twice
            # must not page the whole workspace twice.
            dedupe_key=f"quote_accepted_via_text:{quote.id}",
        )
        log.info("quote_acceptance_operators_notified", parts=len(details))
    except Exception as exc:  # noqa: BLE001 - conversation is already parked
        log.warning("quote_acceptance_notify_failed", error=str(exc))
