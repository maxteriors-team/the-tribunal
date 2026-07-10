"""Google Calendar push-notification webhook.

Google's ``events.watch`` delivers header-only POSTs (no body). We identify the
originating connection by the channel/resource id (and a channel token that we
set equal to the channel id at registration), then run an incremental sync in
the background so the request returns fast. The sync itself reads Google +
updates our DB idempotently, so a spoofed or duplicate notification is harmless.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Request
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.calendar_connection import CalendarConnection
from app.services.calendar.google.oauth import PROVIDER
from app.services.calendar.google.sync import sync_workspace
from app.utils.background_tasks import spawn_background_task

router = APIRouter()
logger = structlog.get_logger()


@router.post("/notifications")
async def google_calendar_notification(request: Request) -> dict[str, str]:
    """Receive an events.watch push and trigger a background sync."""
    log = logger.bind(endpoint="google_calendar_notification")

    resource_state = request.headers.get("X-Goog-Resource-State")
    channel_id = request.headers.get("X-Goog-Channel-ID")
    resource_id = request.headers.get("X-Goog-Resource-ID")
    channel_token = request.headers.get("X-Goog-Channel-Token")

    # The initial handshake after registering a channel — nothing to sync yet.
    if resource_state == "sync":
        return {"status": "ok"}

    if not channel_id:
        return {"status": "ignored"}

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CalendarConnection).where(
                CalendarConnection.provider == PROVIDER,
                CalendarConnection.watch_channel_id == channel_id,
                CalendarConnection.is_active.is_(True),
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            log.info("google_notification_unknown_channel")
            return {"status": "ignored"}

        # Verify the resource + token match what we registered.
        if connection.watch_resource_id and resource_id != connection.watch_resource_id:
            log.warning("google_notification_resource_mismatch")
            return {"status": "ignored"}
        if channel_token and channel_token != channel_id:
            log.warning("google_notification_token_mismatch")
            return {"status": "ignored"}

        workspace_id: uuid.UUID = connection.workspace_id

    spawn_background_task(
        sync_workspace(workspace_id),
        name="google_calendar_sync:webhook",
    )
    return {"status": "ok"}
