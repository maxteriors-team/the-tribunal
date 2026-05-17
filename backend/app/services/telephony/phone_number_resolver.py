"""Shared helper for resolving a workspace's outbound SMS phone number."""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber


async def get_workspace_sms_number(db: AsyncSession, workspace_id: uuid.UUID) -> PhoneNumber | None:
    """Return the workspace's primary outbound SMS number, or None.

    Picks the oldest active, SMS-enabled phone number owned by the workspace.
    """
    result = await db.execute(
        select(PhoneNumber)
        .where(
            and_(
                PhoneNumber.workspace_id == workspace_id,
                PhoneNumber.is_active.is_(True),
                PhoneNumber.sms_enabled.is_(True),
            )
        )
        .order_by(PhoneNumber.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()
