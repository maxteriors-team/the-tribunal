"""Global opt-out list management."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.opt_out import GlobalOptOut

logger = structlog.get_logger()


class OptOutManager:
    """Manage global opt-out list for SMS compliance.

    This service handles:
    - Checking if a phone number is opted out
    - Adding phone numbers to the opt-out list
    - Detecting opt-out keywords in messages
    """

    # Configurable opt-out keywords (case-insensitive)
    OPT_OUT_KEYWORDS: set[str] = {
        "stop",
        "stopall",
        "unsubscribe",
        "cancel",
        "end",
        "quit",
        "opt out",
        "optout",
        "remove",
        "unsub",
    }

    def __init__(self) -> None:
        self.logger = logger.bind(component="opt_out_manager")

    async def check_opt_out(
        self,
        workspace_id: uuid.UUID,
        phone_number: str,
        db: AsyncSession,
    ) -> bool:
        """Check if phone number is on global opt-out list.

        Args:
            workspace_id: Workspace ID
            phone_number: Phone number to check (E.164 format)
            db: Database session

        Returns:
            True if phone number is opted out
        """
        result = await db.execute(
            select(GlobalOptOut).where(
                GlobalOptOut.workspace_id == workspace_id,
                GlobalOptOut.phone_number == phone_number,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_opt_out(
        self,
        workspace_id: uuid.UUID,
        phone_number: str,
        db: AsyncSession,
        keyword: str | None = None,
        source_campaign_id: uuid.UUID | None = None,
        source_message_id: uuid.UUID | None = None,
    ) -> GlobalOptOut | None:
        """Add phone number to global opt-out list.

        Args:
            workspace_id: Workspace ID
            phone_number: Phone number to opt out (E.164 format)
            db: Database session
            keyword: Opt-out keyword used (e.g., "STOP")
            source_campaign_id: Campaign that triggered opt-out
            source_message_id: Message that contained opt-out

        Returns:
            Created GlobalOptOut record, or None if already exists
        """
        # Check if already exists
        existing = await db.execute(
            select(GlobalOptOut).where(
                GlobalOptOut.workspace_id == workspace_id,
                GlobalOptOut.phone_number == phone_number,
            )
        )
        if existing.scalar_one_or_none():
            self.logger.debug(
                "opt_out_already_exists",
                phone_number=phone_number,
                workspace_id=str(workspace_id),
            )
            return None

        # Create new opt-out
        opt_out = GlobalOptOut(
            workspace_id=workspace_id,
            phone_number=phone_number,
            opt_out_keyword=keyword,
            source_campaign_id=source_campaign_id,
            source_message_id=source_message_id,
            opted_out_at=datetime.now(UTC),
        )
        db.add(opt_out)
        await db.commit()
        await db.refresh(opt_out)

        self.logger.info(
            "opt_out_added",
            phone_number=phone_number,
            workspace_id=str(workspace_id),
            keyword=keyword,
        )

        return opt_out

    async def remove_opt_out(
        self,
        workspace_id: uuid.UUID,
        phone_number: str,
        db: AsyncSession,
    ) -> bool:
        """Remove phone number from opt-out list.

        Warning: This should be used carefully for compliance reasons.

        Args:
            workspace_id: Workspace ID
            phone_number: Phone number to remove
            db: Database session

        Returns:
            True if record was removed
        """
        result = await db.execute(
            select(GlobalOptOut).where(
                GlobalOptOut.workspace_id == workspace_id,
                GlobalOptOut.phone_number == phone_number,
            )
        )
        opt_out = result.scalar_one_or_none()

        if opt_out:
            await db.delete(opt_out)
            await db.commit()

            self.logger.warning(
                "opt_out_removed",
                phone_number=phone_number,
                workspace_id=str(workspace_id),
            )
            return True

        return False

    def is_opt_out_keyword(self, message: str) -> tuple[bool, str | None]:
        """Check if message contains an opt-out keyword.

        Args:
            message: Message text to check

        Returns:
            Tuple of (is_opt_out, matched_keyword)
        """
        if not message:
            return False, None

        message_lower = message.lower().strip()

        # Check exact match first
        if message_lower in self.OPT_OUT_KEYWORDS:
            return True, message_lower

        # Check if message starts with opt-out keyword
        for keyword in self.OPT_OUT_KEYWORDS:
            if message_lower.startswith(keyword + " ") or message_lower == keyword:
                return True, keyword

        return False, None

    async def get_opt_out_count(
        self,
        workspace_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """Get count of opted-out phone numbers in workspace.

        Args:
            workspace_id: Workspace ID
            db: Database session

        Returns:
            Count of opted-out numbers
        """
        from sqlalchemy import func

        result = await db.execute(
            select(func.count(GlobalOptOut.id)).where(GlobalOptOut.workspace_id == workspace_id)
        )
        return result.scalar() or 0

    async def get_recent_opt_outs(
        self,
        workspace_id: uuid.UUID,
        db: AsyncSession,
        limit: int = 100,
    ) -> list[GlobalOptOut]:
        """Get recent opt-outs for a workspace.

        Args:
            workspace_id: Workspace ID
            db: Database session
            limit: Maximum number of records to return

        Returns:
            List of recent opt-out records
        """
        result = await db.execute(
            select(GlobalOptOut)
            .where(GlobalOptOut.workspace_id == workspace_id)
            .order_by(GlobalOptOut.opted_out_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
