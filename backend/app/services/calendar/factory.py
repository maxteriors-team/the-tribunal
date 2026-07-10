"""Select the calendar provider for a booking/link operation.

Single decision point so booking code stays provider-neutral. Today every
context resolves to Cal.com; a later migration phase makes
:func:`get_calendar_provider` return the Google provider when a workspace has a
live Google Calendar connection, falling back to Cal.com until it is removed.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.calendar.calcom import CalComCalendarProvider, CalComService
from app.services.calendar.google.availability import resolve_schedule_config
from app.services.calendar.google.client import GoogleCalendarClient
from app.services.calendar.google.oauth import (
    get_connection,
    google_oauth_configured,
    make_token_provider,
)
from app.services.calendar.google.provider import GoogleCalendarProvider
from app.services.calendar.provider import CalendarProvider

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def calcom_provider_for(event_type_id: int) -> CalComCalendarProvider:
    """Build a Cal.com provider bound to ``event_type_id`` from global settings.

    The returned provider owns its underlying ``CalComService``; call
    ``await provider.close()`` when finished with network operations. Pure
    link generation (``reschedule_link``) opens no HTTP client, so worker link
    builders can use it without an explicit close.
    """
    return CalComCalendarProvider(
        CalComService(settings.calcom_api_key),
        event_type_id,
        owns_service=True,
    )


async def get_calendar_provider(
    *,
    event_type_id: int | None = None,
    agent: Any | None = None,
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
    schedule_config: dict[str, Any] | None = None,
    timezone: str = "America/New_York",
) -> CalendarProvider:
    """Return the calendar provider for this booking context.

    Selection order:
    - Google Calendar when the workspace has a live Google connection.
    - Cal.com otherwise (current default).

    Args:
        event_type_id: Cal.com event type to bind for the Cal.com path.
        agent: Booking agent (source of workspace / default event type / schedule).
        workspace_id: Workspace whose Google connection is consulted.
        db: Optional session for the Google-connection lookup (else a transient
            session is opened).
        schedule_config: Weekly-hours config for the Google slot engine; falls
            back to the agent's ``schedule_config``.
        timezone: Default timezone for the Google slot engine.
    """
    google = await _maybe_google_provider(
        workspace_id=workspace_id,
        agent=agent,
        db=db,
        schedule_config=schedule_config,
        timezone=timezone,
    )
    if google is not None:
        return google

    if event_type_id is None:
        raise ValueError("event_type_id is required to build a Cal.com provider")
    return calcom_provider_for(event_type_id)


async def _maybe_google_provider(
    *,
    workspace_id: uuid.UUID | None,
    agent: Any | None,
    db: AsyncSession | None,
    schedule_config: dict[str, Any] | None,
    timezone: str,
) -> GoogleCalendarProvider | None:
    """Build a Google provider when the workspace has a live connection, else None."""
    if workspace_id is None or not google_oauth_configured():
        return None

    calendar_id = await _google_calendar_id(db, workspace_id)
    if calendar_id is None:
        return None

    effective_schedule = schedule_config
    if effective_schedule is None and agent is not None:
        effective_schedule = getattr(agent, "schedule_config", None)

    token_provider = make_token_provider(workspace_id)
    client = GoogleCalendarClient(token_provider, calendar_id)
    schedule = resolve_schedule_config(effective_schedule, default_timezone=timezone)
    return GoogleCalendarProvider(client, schedule, owns_client=True)


async def _google_calendar_id(db: AsyncSession | None, workspace_id: uuid.UUID) -> str | None:
    """Return the connected Google calendar id for a workspace, or None."""
    if db is not None:
        connection = await get_connection(db, workspace_id)
        return (connection.google_calendar_id or "primary") if connection else None
    async with AsyncSessionLocal() as session:
        connection = await get_connection(session, workspace_id)
        return (connection.google_calendar_id or "primary") if connection else None


async def reschedule_link_for_agent(
    agent: Any,
    *,
    contact_email: str,
    contact_name: str,
    contact_phone: str | None = None,
) -> str:
    """Return a provider-neutral reschedule/booking link for an agent's contact.

    Picks the workspace's live provider (Google when connected, else Cal.com).
    Returns ``""`` when the agent has no bookable calendar configured, so callers
    can fall back to a "reply to reschedule" message. The Google path returns our
    own reschedule link (empty until a hosted reschedule flow exists).
    """
    workspace_id = getattr(agent, "workspace_id", None)
    calcom_event_type_id = getattr(agent, "calcom_event_type_id", None)
    calcom_ready = bool(calcom_event_type_id) and bool(settings.calcom_api_key)
    google_ready = workspace_id is not None and google_oauth_configured()
    if not calcom_ready and not google_ready:
        return ""

    try:
        provider = await get_calendar_provider(
            event_type_id=calcom_event_type_id if calcom_ready else None,
            agent=agent,
            workspace_id=workspace_id,
            schedule_config=getattr(agent, "schedule_config", None),
        )
    except ValueError:
        return ""

    try:
        return provider.reschedule_link(
            contact_email=contact_email,
            contact_name=contact_name,
            contact_phone=contact_phone,
        )
    finally:
        await provider.close()
