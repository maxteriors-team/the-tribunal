"""Shared workspace phone-number resolution helpers."""

import uuid
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber


async def resolve_workspace_phone_number(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    phone_number: str | None = None,
    *,
    capability: Literal["text", "voice"] | None = None,
) -> PhoneNumber | None:
    """Resolve an active phone number owned by a workspace.

    When requested, ``text`` accepts either SMS or iMessage capability, while
    ``voice`` requires voice capability.
    """
    filters = [
        PhoneNumber.workspace_id == workspace_id,
        PhoneNumber.is_active.is_(True),
    ]
    if phone_number is not None:
        filters.append(PhoneNumber.phone_number == phone_number)

    if capability == "text":
        filters.append(
            or_(
                PhoneNumber.sms_enabled.is_(True),
                PhoneNumber.imessage_enabled.is_(True),
            )
        )
    elif capability == "voice":
        filters.append(PhoneNumber.voice_enabled.is_(True))
    elif capability is not None:
        raise ValueError(f"Unsupported phone number capability: {capability}")

    result = await db.execute(
        select(PhoneNumber).where(*filters).order_by(PhoneNumber.created_at.asc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_workspace_sms_number(db: AsyncSession, workspace_id: uuid.UUID) -> PhoneNumber | None:
    """Return the workspace's first active text-capable sender, if any."""
    return await resolve_workspace_phone_number(db, workspace_id, capability="text")
