"""Message test worker service for processing A/B test messages.

This background worker:
1. Polls for running message tests
2. Assigns variants using round-robin distribution
3. Sends ONE message per contact with their assigned variant
4. Updates variant stats on send
5. Supports number pooling and rotation
6. Enforces global opt-out list
"""

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.message_test import (
    MessageTest,
    MessageTestStatus,
    TestContact,
    TestContactStatus,
)
from app.services.rate_limiting.number_pool import NumberPoolManager
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.rate_limiting.rate_limiter import RateLimiter
from app.services.rate_limiting.reputation_tracker import ReputationTracker
from app.services.telephony.telnyx import TelnyxSMSService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Worker configuration
MAX_MESSAGES_PER_TICK = 20


class MessageTestWorker(RetryableWorker, BaseWorker):
    """Background worker for processing message tests with round-robin variant assignment."""

    POLL_INTERVAL_SECONDS = settings.campaign_poll_interval
    COMPONENT_NAME = "message_test_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        # Rate limiting services (Redis-based)
        self.number_pool = NumberPoolManager()
        self.rate_limiter = RateLimiter()
        self.opt_out_manager = OptOutManager()
        self.reputation_tracker = ReputationTracker()

    async def _process_items(self) -> None:
        """Process all running message tests."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MessageTest)
                .options(
                    selectinload(MessageTest.agent),
                    selectinload(MessageTest.variants),
                )
                .where(MessageTest.status == MessageTestStatus.RUNNING)
            )
            tests = result.scalars().all()

            if not tests:
                return

            self.logger.debug("Processing message tests", count=len(tests))

            for test in tests:
                await self.execute_with_retry(
                    self._process_test,
                    test,
                    db,
                    item_key=f"message_test:{test.id}",
                )

    async def _process_test(self, test: MessageTest, db: AsyncSession) -> None:
        """Process a single message test."""
        log = self.logger.bind(
            test_id=str(test.id),
            test_name=test.name,
        )

        # Get SMS service
        if not settings.telnyx_api_key:
            log.warning("No Telnyx API key configured")
            return

        sms_service = TelnyxSMSService(settings.telnyx_api_key)
        try:
            await self._process_pending_contacts(test, sms_service, db, log)

            # Check if test is complete
            await self._check_completion(test, db, log)

            await db.commit()
        finally:
            await sms_service.close()

    async def _get_pending_contacts(
        self, test: MessageTest, db: AsyncSession
    ) -> list[TestContact]:
        """Get pending contacts for the test with row-level locking."""
        pending_result = await db.execute(
            select(TestContact)
            .options(selectinload(TestContact.contact))
            .where(
                and_(
                    TestContact.message_test_id == test.id,
                    TestContact.status == TestContactStatus.PENDING,
                    TestContact.opted_out.is_(False),
                )
            )
            .order_by(TestContact.created_at)
            .limit(MAX_MESSAGES_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        return list(pending_result.scalars().all())

    async def _send_test_message(
        self,
        test: MessageTest,
        test_contact: TestContact,
        variant: Any,
        from_phone: Any,
        sms_service: TelnyxSMSService,
        db: AsyncSession,
        log: Any,
    ) -> bool:
        """Send a test message and update stats. Returns True on success."""
        contact = test_contact.contact
        message_text = self._render_template(variant.message_template, contact)

        message = await sms_service.send_message(
            to_number=contact.phone_number,
            from_number=from_phone.phone_number,
            body=message_text,
            db=db,
            workspace_id=test.workspace_id,
            agent_id=test.agent_id,
            phone_number_id=from_phone.id,
        )

        from_phone.last_sent_at = datetime.now(UTC)
        await self.reputation_tracker.increment_sent(from_phone.id, db)

        test_contact.variant_id = variant.id
        test_contact.variant_assigned_at = datetime.now(UTC)
        test_contact.status = TestContactStatus.SENT
        test_contact.conversation_id = message.conversation_id
        test_contact.first_sent_at = datetime.now(UTC)

        variant.contacts_assigned += 1
        variant.messages_sent += 1
        variant.update_rates()
        test.messages_sent += 1

        await self._assign_agent_to_conversation(test, message, db)

        log.info(
            "Test message sent",
            contact_id=contact.id,
            variant_id=str(variant.id),
            message_id=str(message.id),
        )
        return True

    async def _assign_agent_to_conversation(
        self, test: MessageTest, message: Any, db: AsyncSession
    ) -> None:
        """Assign test's AI agent to the conversation."""
        if test.agent_id and message.conversation_id:
            from app.models.conversation import Conversation

            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == message.conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv:
                conv.assigned_agent_id = test.agent_id
                conv.ai_enabled = test.ai_enabled

    async def _process_pending_contacts(
        self,
        test: MessageTest,
        sms_service: TelnyxSMSService,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Process and send messages to pending contacts with round-robin variant assignment."""
        rate_ok = await self.rate_limiter.check_campaign_rate_limit(
            test.id, test.messages_per_minute
        )
        if not rate_ok:
            log.debug("Test rate limit reached")
            return

        pending_contacts = await self._get_pending_contacts(test, db)
        if not pending_contacts:
            return

        log.info("Sending test messages", count=len(pending_contacts))

        variants = sorted(test.variants, key=lambda v: v.sort_order)
        if not variants:
            log.warning("No variants configured for test")
            return

        sent_count = 0
        for test_contact in pending_contacts:
            result = await self._process_single_contact(
                test, test_contact, variants, sms_service, db, log
            )
            if result == "sent":
                sent_count += 1
            elif result == "break":
                break

        if sent_count > 0:
            log.info("Test messages batch complete", sent=sent_count)

    async def _process_single_contact(
        self,
        test: MessageTest,
        test_contact: TestContact,
        variants: list[Any],
        sms_service: TelnyxSMSService,
        db: AsyncSession,
        log: Any,
    ) -> str:
        """Process a single contact. Returns 'sent', 'skip', or 'break'."""
        contact = test_contact.contact
        if not contact or not contact.phone_number:
            test_contact.status = TestContactStatus.FAILED
            test_contact.last_error = "missing_phone_number"
            return "skip"

        is_opted_out = await self.opt_out_manager.check_opt_out(
            test.workspace_id, contact.phone_number, db
        )
        if is_opted_out:
            test_contact.status = TestContactStatus.OPTED_OUT
            test_contact.opted_out = True
            test_contact.opted_out_at = datetime.now(UTC)
            return "skip"

        variant = min(variants, key=lambda v: v.contacts_assigned)
        from_phone = await self.number_pool.get_next_available_number_for_test(test, db)

        if not from_phone:
            log.warning("No available numbers in pool, pausing sending")
            return "break"

        try:
            await self._send_test_message(
                test, test_contact, variant, from_phone, sms_service, db, log
            )
            return "sent"
        except Exception as e:
            log.exception("Failed to send test message", contact_id=contact.id, error=str(e))
            test_contact.status = TestContactStatus.FAILED
            test_contact.last_error = str(e)
            test.error_count += 1
            test.last_error = str(e)
            return "skip"

    async def _check_completion(
        self,
        test: MessageTest,
        db: AsyncSession,
        log: Any,
    ) -> None:
        """Check if message test is complete."""
        remaining_result = await db.execute(
            select(func.count(TestContact.id)).where(
                and_(
                    TestContact.message_test_id == test.id,
                    TestContact.status == TestContactStatus.PENDING,
                )
            )
        )
        remaining = remaining_result.scalar() or 0

        if remaining == 0:
            log.info("All contacts processed, completing test")
            test.status = MessageTestStatus.COMPLETED
            test.completed_at = datetime.now(UTC)

    def _render_template(
        self,
        template: str,
        contact: Contact,
    ) -> str:
        """Render message template with contact data."""
        try:
            message = template
            full_name = " ".join(filter(None, [contact.first_name, contact.last_name])) or ""

            replacements: dict[str, str] = {
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "full_name": full_name,
                "company_name": contact.company_name or "",
                "email": contact.email or "",
            }

            # Replace placeholders safely (case-insensitive)
            for placeholder, value in replacements.items():
                try:
                    pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
                    message = pattern.sub(value, message)
                except Exception as e:
                    self.logger.warning(
                        "placeholder_replacement_error",
                        placeholder=placeholder,
                        error=str(e),
                    )

            return message

        except Exception as e:
            self.logger.error(
                "template_rendering_failed",
                error=str(e),
                template_length=len(template) if template else 0,
            )
            return template


# Singleton registry
_registry = WorkerRegistry(MessageTestWorker)
start_message_test_worker = _registry.start
stop_message_test_worker = _registry.stop
get_message_test_worker = _registry.get
