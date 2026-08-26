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

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.email import send_event_notification_email
from app.services.idempotency import derive_outbound_key
from app.services.notification_recipients import workspace_notification_email_users
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
    recipient_count: int = 0
    delivered_recipient_count: int = 0
    failed_recipient_count: int = 0
    delivered_recipient_ids: tuple[int, ...] = ()
    failed_recipient_ids: tuple[int, ...] = ()


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
    recipient_user_ids: Sequence[int] | None = None,
) -> NotificationDispatchResult:
    """Send an actionable-event notification for a workspace.

    Push remains workspace-wide. Email goes to global operators unless callers
    explicitly target member IDs, and still respects user notification preferences
    plus per-event idempotency.
    """
    workspace_id_str = str(workspace_id)
    recipients = tuple(dict.fromkeys(recipient_user_ids or ()))

    push_recipient_ids = await _send_push(
        db,
        workspace_id=workspace_id_str,
        notification_type=notification_type,
        title=title,
        body=body,
        data=data,
        channel_id=channel_id,
        dedupe_key=dedupe_key,
        recipient_user_ids=recipients or None,
    )

    email_recipient_ids: tuple[int, ...] = ()
    eligible_email_recipient_ids: tuple[int, ...] = ()
    if email_subject is not None:
        email_recipient_ids, eligible_email_recipient_ids = await _send_emails(
            db,
            workspace_id=workspace_id_str,
            notification_type=notification_type,
            subject=email_subject,
            heading=email_heading or title,
            intro=email_intro or body,
            details=email_details,
            dedupe_key=dedupe_key,
            recipient_user_ids=recipients or None,
        )

    recipient_set = set(recipients or eligible_email_recipient_ids or push_recipient_ids)
    delivered_ids = tuple(sorted(set(push_recipient_ids) | set(email_recipient_ids)))
    failed_ids = tuple(sorted(recipient_set - set(delivered_ids)))
    return NotificationDispatchResult(
        push_sent=bool(push_recipient_ids),
        emails_sent=len(email_recipient_ids),
        recipient_count=len(recipient_set),
        delivered_recipient_count=len(delivered_ids),
        failed_recipient_count=len(failed_ids),
        delivered_recipient_ids=delivered_ids,
        failed_recipient_ids=failed_ids,
    )


async def _send_push(
    db: AsyncSession,
    *,
    workspace_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict[str, Any] | None,
    channel_id: str | None,
    dedupe_key: str | uuid.UUID | None,
    recipient_user_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    try:
        if recipient_user_ids is not None:
            sent_ids: list[int] = []
            for user_id in recipient_user_ids:
                sent = await push_notification_service.send_to_user(
                    db,
                    user_id,
                    title,
                    body,
                    data,
                    notification_type,
                    channel_id,
                    idempotency_key=str(dedupe_key) if dedupe_key is not None else None,
                )
                if sent:
                    sent_ids.append(user_id)
            return tuple(sent_ids)
        sent = await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=workspace_id,
            title=title,
            body=body,
            data=data,
            notification_type=notification_type,
            channel_id=channel_id,
        )
        # Legacy workspace-wide callers consume only the aggregate boolean.
        return (-1,) if sent else ()
    except Exception:
        logger.exception(
            "actionable_event_push_failed type=%s workspace=%s",
            notification_type,
            workspace_id,
        )
        return ()


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
    recipient_user_ids: Sequence[int] | None,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Email opted-in global operators, or any explicitly targeted members."""
    pref_attr = NOTIFICATION_TYPE_PREFS.get(notification_type)
    members = await workspace_notification_email_users(
        db,
        workspace_id,
        recipient_user_ids=recipient_user_ids,
    )

    detail_dict = dict(details) if details else None
    sent_ids: list[int] = []
    eligible_ids: list[int] = []
    for user in members:
        if not user.email or not user.notification_email:
            continue
        if pref_attr is not None and not getattr(user, pref_attr, True):
            continue
        eligible_ids.append(user.id)
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
        if ok:
            sent_ids.append(user.id)

    logger.info(
        "actionable_event_email_dispatched type=%s recipients=%s eligible=%s",
        notification_type,
        len(sent_ids),
        len(eligible_ids),
    )
    return tuple(sent_ids), tuple(eligible_ids)


__all__: Sequence[str] = ("NotificationDispatchResult", "notify_workspace_event")
