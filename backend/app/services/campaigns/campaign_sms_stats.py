"""Campaign SMS stats service.

Updates campaign and campaign_contact stats for SMS reply and delivery events.
"""

from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus

# Statuses that represent a final SMS delivery outcome. Once a message is in
# one of these, subsequent provider webhooks for the same message should not
# move campaign counters again.
_TERMINAL_DELIVERY_STATUSES = frozenset({"delivered", "failed"})


async def update_campaign_sms_reply(
    db: AsyncSession,
    conversation_id: UUID,
    log: structlog.BoundLogger,
) -> None:
    """Update campaign stats when a contact replies to an SMS.

    Args:
        db: Database session
        conversation_id: Conversation ID from the inbound message
        log: Logger instance
    """
    cc_result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.campaign))
        .where(CampaignContact.conversation_id == conversation_id)
    )
    campaign_contact = cc_result.scalar_one_or_none()

    if not campaign_contact:
        log.debug("not_a_campaign_reply", conversation_id=str(conversation_id))
        return

    campaign = campaign_contact.campaign
    if not campaign:
        log.warning("missing_campaign_for_sms_reply", conversation_id=str(conversation_id))
        return

    campaign.replies_received += 1
    campaign_contact.status = CampaignContactStatus.REPLIED
    campaign_contact.messages_received += 1
    campaign_contact.last_reply_at = datetime.now(UTC)

    await db.commit()
    log.info(
        "campaign_sms_reply_recorded",
        campaign_id=str(campaign.id),
        campaign_contact_id=str(campaign_contact.id),
    )


async def update_campaign_sms_delivery(
    db: AsyncSession,
    conversation_id: UUID,
    delivered: bool,
    log: structlog.BoundLogger,
    previous_status: str | None = None,
) -> None:
    """Update campaign stats for SMS delivery or failure.

    Telnyx (and most SMS providers) routinely fire multiple webhooks for the
    same physical message — e.g. ``message.sent`` followed by
    ``message.finalized``, plus retries on transient HTTP failures. Without
    deduplication, ``messages_delivered`` / ``messages_failed`` would be
    incremented on every redelivery.

    To keep counters consistent we:

    * Skip the increment entirely when ``previous_status`` is already the
      same terminal state we're transitioning into (duplicate webhook).
    * Apply the increment as an atomic SQL ``UPDATE ... SET col = col + 1``
      so concurrent webhooks for *different* messages of the same campaign
      can't lose updates due to read-modify-write races.

    Args:
        db: Database session
        conversation_id: Conversation ID from the delivery status update
        delivered: True if delivered, False if failed
        log: Logger instance
        previous_status: The message's status prior to this webhook being
            applied. Used to detect duplicate/redelivered webhooks. When
            ``None`` we conservatively still apply the increment (preserves
            behaviour for legacy callers that don't supply it).
    """
    cc_result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.campaign))
        .where(CampaignContact.conversation_id == conversation_id)
    )
    campaign_contact = cc_result.scalar_one_or_none()

    if not campaign_contact:
        log.debug("not_a_campaign_delivery", conversation_id=str(conversation_id))
        return

    campaign = campaign_contact.campaign
    if not campaign:
        log.warning("missing_campaign_for_sms_delivery", conversation_id=str(conversation_id))
        return

    new_status = "delivered" if delivered else "failed"

    # Dedup: if the message was already in a terminal state, this webhook is
    # a duplicate (Telnyx redelivery, or sent+finalized both arriving as
    # final) and must NOT bump campaign counters again.
    if previous_status is not None and previous_status in _TERMINAL_DELIVERY_STATUSES:
        log.info(
            "campaign_sms_delivery_dedup_skipped",
            campaign_id=str(campaign.id),
            campaign_contact_id=str(campaign_contact.id),
            previous_status=previous_status,
            new_status=new_status,
        )
        return

    # Atomic counter bump. Using an UPDATE expression instead of
    # ``campaign.messages_delivered += 1`` avoids the read-modify-write race
    # when multiple webhooks for different messages of the same campaign
    # arrive concurrently and load stale snapshots of the counter.
    counter_column = (
        Campaign.messages_delivered if delivered else Campaign.messages_failed
    )
    await db.execute(
        update(Campaign)
        .where(Campaign.id == campaign.id)
        .values({counter_column: counter_column + 1})
    )

    if delivered:
        if campaign_contact.status == CampaignContactStatus.SENT:
            campaign_contact.status = CampaignContactStatus.DELIVERED
        log.info(
            "campaign_sms_delivered",
            campaign_id=str(campaign.id),
            campaign_contact_id=str(campaign_contact.id),
            previous_status=previous_status,
        )
    else:
        log.info(
            "campaign_sms_failed",
            campaign_id=str(campaign.id),
            campaign_contact_id=str(campaign_contact.id),
            previous_status=previous_status,
        )

    await db.commit()
