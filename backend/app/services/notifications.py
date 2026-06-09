"""Unified actionable-event notifications (push + email to workspace members).

Originating services (reviews, deal coach, missed-call text-back, roleplay,
automation worker) call :func:`notify_workspace_event` to fan a single domain
event out to every workspace operator over both push and email, while honoring
each user's master toggles (``notification_push`` / ``notification_email``) and
the per-type preference column mapped from ``notification_type`` in
:data:`app.services.push_notifications.NOTIFICATION_TYPE_PREFS`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.email import send_event_notification_email
from app.services.idempotency import derive_outbound_key
from app.services.push_notifications import (
    NOTIFICATION_TYPE_PREFS,
    push_notification_service,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NotificationDispatchResult:
    """Outcome of an actionable-event notification fan-out."""

    push_sent: bool
    emails_sent: int


async def notify_workspace_event(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | str,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    channel_id: str | None = None,
    email_subject: str | None = None,
    email_heading: str | None = None,
    email_intro: str | None = None,
    email_details: Mapping[str, str] | None = None,
    dedupe_key: str | uuid.UUID | None = None,
) -> NotificationDispatchResult:
    """Send an actionable-event notification to every workspace member.

    Push is delivered through :class:`PushNotificationService`, which already
    enforces the master push toggle and the per-type preference. Email is sent
    when ``email_subject`` is provided, gated by each user's master email
    toggle *and* the same per-type preference, and deduplicated per
    (event, user) via ``dedupe_key`` so retries never double-send.
    """
    workspace_id_str = str(workspace_id)

    push_sent = await _send_push(
        db,
        workspace_id=workspace_id_str,
        notification_type=notification_type,
        title=title,
        body=body,
        data=data,
        channel_id=channel_id,
    )

    emails_sent = 0
    if email_subject is not None:
        emails_sent = await _send_emails(
            db,
            workspace_id=workspace_id_str,
            notification_type=notification_type,
            subject=email_subject,
            heading=email_heading or title,
            intro=email_intro or body,
            details=email_details,
            dedupe_key=dedupe_key,
        )

    return NotificationDispatchResult(push_sent=push_sent, emails_sent=emails_sent)


async def _send_push(
    db: AsyncSession,
    *,
    workspace_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, Any] | None,
    channel_id: str | None,
) -> bool:
    try:
        return await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=workspace_id,
            title=title,
            body=body,
            data=data,
            notification_type=notification_type,
            channel_id=channel_id,
        )
    except Exception:
        logger.exception(
            "actionable_event_push_failed type=%s workspace=%s",
            notification_type,
            workspace_id,
        )
        return False


async def _send_emails(
    db: AsyncSession,
    *,
    workspace_id: str,
    notification_type: str,
    subject: str,
    heading: str,
    intro: str,
    details: Mapping[str, str] | None,
    dedupe_key: str | uuid.UUID | None,
) -> int:
    """Email each opted-in workspace member about the event."""
    pref_attr = NOTIFICATION_TYPE_PREFS.get(notification_type)
    workspace = await db.get(Workspace, uuid.UUID(workspace_id))
    if workspace is None:
        return 0

    members = await db.execute(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace.id)
    )

    detail_dict = dict(details) if details else None
    sent = 0
    for user in members.scalars().all():
        if not user.email or not user.notification_email:
            continue
        if pref_attr is not None and not getattr(user, pref_attr, True):
            continue
        idem = derive_outbound_key(
            f"{notification_type}_email",
            dedupe_key if dedupe_key is not None else subject,
            user.id,
        )
        try:
            ok = await send_event_notification_email(
                to_email=user.email,
                subject=subject,
                heading=heading,
                intro=intro,
                details=detail_dict,
                idempotency_key=idem,
            )
        except Exception:
            logger.exception(
                "actionable_event_email_failed type=%s user=%s",
                notification_type,
                user.id,
            )
            ok = False
        sent += 1 if ok else 0

    logger.info(
        "actionable_event_email_dispatched type=%s recipients=%s",
        notification_type,
        sent,
    )
    return sent


__all__: Sequence[str] = ("NotificationDispatchResult", "notify_workspace_event")
