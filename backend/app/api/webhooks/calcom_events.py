"""Downstream event dispatch helpers for Cal.com webhooks.

Side-effect-heavy helpers extracted from ``calcom.py``:
- Workspace owner lookup for appointment email notifications
- Campaign resolution for new appointments
- Recent voice-message linking

Lifecycle SMS rendering/sending now lives in
:mod:`app.services.appointments.lifecycle_sms` because the AI agents book
locally too — this webhook is only one of its callers. Those names are
re-exported here so the webhook handlers keep a single import site.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select

from app.models.campaign import Campaign, CampaignContact
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.appointments.lifecycle_sms import (
    DEFAULT_CONFIRMATION_BODY,
    build_confirmation_body,
    resolve_sms_from_number,
    send_lifecycle_sms,
)

logger = structlog.get_logger()

# Re-exported for handler convenience.
__all__ = [
    "DEFAULT_CONFIRMATION_BODY",
    "build_confirmation_body",
    "find_recent_voice_message",
    "get_workspace_owner",
    "resolve_campaign_id",
    "resolve_sms_from_number",
    "send_lifecycle_sms",
]


async def find_recent_voice_message(
    db: Any,
    contact_id: int,
    agent_id: Any,
    log: Any,
) -> Any:
    """Find a recent voice message for a contact+agent (within 10 minutes)."""
    try:
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        msg_query = (
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.contact_id == contact_id,
                Message.channel == "voice",
                Message.created_at >= cutoff,
            )
        )
        if agent_id:
            msg_query = msg_query.where(Message.agent_id == agent_id)
        msg_query = msg_query.order_by(Message.created_at.desc()).limit(1)
        msg_result = await db.execute(msg_query)
        recent_msg = msg_result.scalar_one_or_none()
        if recent_msg:
            msg_id: uuid.UUID = recent_msg.id
            log.info("linked_appointment_to_message", message_id=str(msg_id))
            return msg_id
    except Exception as e:
        log.warning("message_linking_failed", error=str(e))
    return None


async def get_workspace_owner(
    db: Any,
    workspace_id: uuid.UUID,
) -> tuple[str, str] | None:
    """Return ``(email, full_name)`` for the workspace owner or first admin.

    Falls back to the first member if no owner/admin exists.
    Returns ``None`` when the workspace has no members.
    """
    for role in ("owner", "admin", "member"):
        result = await db.execute(
            select(User.email, User.full_name)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == role,
            )
            .limit(1)
        )
        row = result.first()
        if row:
            email: str = row[0]
            full_name: str = row[1] or email.split("@")[0]
            return email, full_name
    return None


async def resolve_campaign_id(db: Any, contact_id: int, log: Any) -> Any:
    """Find the most recent active campaign for a contact."""
    try:
        cc_result = await db.execute(
            select(CampaignContact.campaign_id)
            .join(Campaign, CampaignContact.campaign_id == Campaign.id)
            .where(
                CampaignContact.contact_id == contact_id,
                Campaign.status.in_(["running", "paused"]),
            )
            .order_by(CampaignContact.created_at.desc())
            .limit(1)
        )
        cc_row = cc_result.first()
        if cc_row:
            log.info("resolved_campaign_for_appointment", campaign_id=str(cc_row[0]))
            return cc_row[0]
    except Exception as e:
        log.warning("campaign_resolution_failed", error=str(e))
    return None
