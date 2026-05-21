"""Follow-up worker service for processing automated conversation follow-ups.

This background worker:
1. Polls for conversations with scheduled follow-ups
2. Generates AI follow-up messages
3. Sends messages via Telnyx SMS
4. Updates conversation follow-up tracking
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.conversation import Conversation
from app.services.ai.openai_credentials import get_openai_bearer_token
from app.services.ai.text_response_generator import generate_followup_message
from app.services.telephony.text_provider import get_text_message_provider
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Worker configuration
MAX_FOLLOWUPS_PER_TICK = 10


class FollowupWorker(RetryableWorker, BaseWorker):
    """Background worker for processing conversation follow-ups."""

    POLL_INTERVAL_SECONDS = 60
    COMPONENT_NAME = "followup_worker"
    # Per-conversation follow-up sends; conservative to protect the DB pool.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Process all pending follow-ups."""
        async with AsyncSessionLocal() as db:
            now = datetime.now(UTC)

            # Query conversations that need follow-ups
            result = await db.execute(
                select(Conversation)
                .where(
                    and_(
                        Conversation.followup_enabled.is_(True),
                        Conversation.next_followup_at.is_not(None),
                        Conversation.next_followup_at <= now,
                        Conversation.followup_count_sent < Conversation.followup_max_count,
                        Conversation.ai_enabled.is_(True),
                        # Only follow up if last message was outbound (no reply)
                        Conversation.last_message_direction == "outbound",
                    )
                )
                .order_by(Conversation.next_followup_at)
                .limit(MAX_FOLLOWUPS_PER_TICK)
            )
            conversations = result.scalars().all()

            if not conversations:
                return

            self.logger.info("Processing follow-ups", count=len(conversations))

            for conversation in conversations:
                ok = await self.execute_with_retry(
                    self._process_conversation_followup,
                    conversation,
                    db,
                    item_key=f"conversation:{conversation.id}",
                )
                if ok:
                    self.record_items_processed()

    async def _process_conversation_followup(
        self,
        conversation: Conversation,
        db: AsyncSession,
    ) -> bool:
        """Process follow-up for a single conversation.

        Returns:
            True on a successful invocation (regardless of whether a message
            was actually sent), so the caller knows the retry helper did not
            give up. Raises on transient errors so ``execute_with_retry``
            can back off and try again.
        """
        log = self.logger.bind(conversation_id=str(conversation.id))

        # Check for required credentials
        openai_key = get_openai_bearer_token()
        if not openai_key:
            log.warning("No OpenAI credential configured")
            return False

        # Generate follow-up message
        message_body = await generate_followup_message(
            conversation=conversation,
            db=db,
            openai_api_key=openai_key,
        )

        if not message_body:
            log.warning("Failed to generate follow-up message")
            # Still schedule next attempt
            conversation.next_followup_at = datetime.now(UTC) + timedelta(
                hours=conversation.followup_delay_hours
            )
            await db.commit()
            return False

        # Send the follow-up via SMS
        sms_service = get_text_message_provider()
        try:
            message = await sms_service.send_message(
                to_number=conversation.contact_phone,
                from_number=conversation.workspace_phone,
                body=message_body,
                db=db,
                workspace_id=conversation.workspace_id,
            )

            log.info(
                "Follow-up sent",
                message_id=str(message.id),
                followup_count=conversation.followup_count_sent + 1,
            )

            # Update follow-up tracking
            conversation.followup_count_sent += 1
            conversation.last_followup_at = datetime.now(UTC)

            # Schedule next follow-up if still within limits
            if conversation.followup_count_sent < conversation.followup_max_count:
                conversation.next_followup_at = datetime.now(UTC) + timedelta(
                    hours=conversation.followup_delay_hours
                )
            else:
                conversation.next_followup_at = None
                log.info("Max follow-ups reached", max_count=conversation.followup_max_count)

            await db.commit()
            return True
        finally:
            await sms_service.close()


# Singleton registry
_registry = WorkerRegistry(FollowupWorker)
start_followup_worker = _registry.start
stop_followup_worker = _registry.stop
get_followup_worker = _registry.get
