"""Push notification service using Expo Push API."""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.device_token import DeviceToken
from app.models.user import User
from app.models.workspace import WorkspaceMembership

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# Map notification_type to the user preference column name
NOTIFICATION_TYPE_PREFS = {
    "call": "notification_push_calls",
    "message": "notification_push_messages",
    "voicemail": "notification_push_voicemail",
    "appointment": "notification_push_appointments",
}


class PushNotificationService:
    """Sends push notifications via the Expo Push API."""

    async def send_to_user(
        self,
        db: AsyncSession,
        user_id: int,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> None:
        """Send a push notification to all devices of a user.

        Checks the user's master push toggle and per-type preference before sending.
        """
        # Fetch user to check preferences
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return

        # Check master push toggle
        if not user.notification_push:
            return

        # Check per-type preference
        if notification_type and notification_type in NOTIFICATION_TYPE_PREFS:
            pref_attr = NOTIFICATION_TYPE_PREFS[notification_type]
            if not getattr(user, pref_attr, True):
                return

        # Fetch device tokens
        tokens_result = await db.execute(
            select(DeviceToken.expo_push_token).where(DeviceToken.user_id == user_id)
        )
        tokens = [row[0] for row in tokens_result.all()]

        if not tokens:
            return

        await self._send_notifications(tokens, title, body, data, channel_id)

    async def send_to_workspace_members(
        self,
        db: AsyncSession,
        workspace_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> None:
        """Send a push notification to all members of a workspace."""
        # Get all workspace member user IDs
        result = await db.execute(
            select(WorkspaceMembership.user_id).where(
                WorkspaceMembership.workspace_id == workspace_id
            )
        )
        user_ids = [row[0] for row in result.all()]

        for user_id in user_ids:
            try:
                await self.send_to_user(
                    db, user_id, title, body, data, notification_type, channel_id
                )
            except Exception:
                logger.exception("Failed to send push to user %s", user_id)

    async def _send_notifications(
        self,
        tokens: list[str],
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        channel_id: str | None = None,
    ) -> None:
        """Send push notifications to a list of Expo push tokens."""
        messages = []
        for token in tokens:
            message: dict[str, Any] = {
                "to": token,
                "title": title,
                "body": body,
                "sound": "default",
            }
            if data:
                message["data"] = data
            if channel_id:
                message["channelId"] = channel_id
            messages.append(message)

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if settings.expo_access_token:
            headers["Authorization"] = f"Bearer {settings.expo_access_token}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(EXPO_PUSH_URL, json=messages, headers=headers)
                response.raise_for_status()

                result = response.json()
                # Log errors for individual tokens (e.g., DeviceNotRegistered)
                if "data" in result:
                    for i, item in enumerate(result["data"]):
                        if item.get("status") == "error":
                            logger.warning(
                                "Push error for token %s: %s - %s",
                                tokens[i] if i < len(tokens) else "unknown",
                                item.get("details", {}).get("error", "unknown"),
                                item.get("message", ""),
                            )
        except httpx.HTTPError:
            logger.exception("Failed to send push notifications via Expo")


push_notification_service = PushNotificationService()
