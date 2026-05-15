"""Message test service - business logic orchestration layer."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.contact import Contact
from app.models.message_test import (
    MessageTest,
    MessageTestStatus,
    TestContact,
    TestContactStatus,
    TestVariant,
)
from app.schemas.message_test import (
    ConvertToCampaignRequest,
    MessageTestAnalytics,
    MessageTestCreate,
    MessageTestResponse,
    MessageTestUpdate,
    PaginatedMessageTests,
    TestContactAdd,
    TestContactResponse,
    TestVariantCreate,
    TestVariantResponse,
    TestVariantUpdate,
    VariantAnalytics,
)
from app.services.message_tests.exceptions import (
    AgentNotFoundError,
    MessageTestNotFoundError,
    MessageTestValidationError,
    VariantNotFoundError,
)
from app.utils.datetime import parse_time_string

logger = structlog.get_logger()


class MessageTestService:
    """High-level message test service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="message_test")

    # === Private helpers ===

    async def _get_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> MessageTest:
        """Fetch a message test by ID or raise 404."""
        result = await self.db.execute(
            select(MessageTest).where(
                MessageTest.id == test_id,
                MessageTest.workspace_id == workspace_id,
            )
        )
        message_test = result.scalar_one_or_none()
        if not message_test:
            raise MessageTestNotFoundError()
        return message_test

    async def _get_test_with_variants(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> MessageTest:
        """Fetch a message test with variants loaded, or raise 404."""
        result = await self.db.execute(
            select(MessageTest)
            .options(selectinload(MessageTest.variants))
            .where(
                MessageTest.id == test_id,
                MessageTest.workspace_id == workspace_id,
            )
        )
        message_test = result.scalar_one_or_none()
        if not message_test:
            raise MessageTestNotFoundError()
        return message_test

    def _require_draft_or_paused(self, test: MessageTest, action: str = "modify") -> None:
        """Raise if test is not in draft or paused status."""
        if test.status not in ("draft", "paused"):
            raise MessageTestValidationError(f"Can only {action} draft or paused tests")

    # === Message Test CRUD ===

    async def list_tests(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
    ) -> PaginatedMessageTests:
        """List message tests in a workspace."""
        query = select(MessageTest).where(MessageTest.workspace_id == workspace_id)

        if status_filter:
            query = query.where(MessageTest.status == status_filter)

        query = query.order_by(MessageTest.created_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)

        return PaginatedMessageTests(
            items=[MessageTestResponse.model_validate(t) for t in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )

    async def create_test(
        self,
        workspace_id: uuid.UUID,
        test_data: MessageTestCreate,
    ) -> MessageTest:
        """Create a new message test with optional variants."""
        # Verify agent if provided
        if test_data.agent_id:
            agent_result = await self.db.execute(
                select(Agent).where(
                    Agent.id == test_data.agent_id,
                    Agent.workspace_id == workspace_id,
                )
            )
            if not agent_result.scalar_one_or_none():
                raise AgentNotFoundError()

        # Convert time strings to datetime.time objects
        data = test_data.model_dump(exclude={"variants"})
        if "sending_hours_start" in data:
            data["sending_hours_start"] = parse_time_string(data["sending_hours_start"])
        if "sending_hours_end" in data:
            data["sending_hours_end"] = parse_time_string(data["sending_hours_end"])

        message_test = MessageTest(
            workspace_id=workspace_id,
            **data,
        )
        self.db.add(message_test)
        await self.db.flush()

        # Create variants if provided
        if test_data.variants:
            for variant_data in test_data.variants:
                variant = TestVariant(
                    message_test_id=message_test.id,
                    **variant_data.model_dump(),
                )
                self.db.add(variant)
                message_test.total_variants += 1

        await self.db.commit()
        await self.db.refresh(message_test)

        # Reload with variants
        result = await self.db.execute(
            select(MessageTest)
            .options(selectinload(MessageTest.variants))
            .where(MessageTest.id == message_test.id)
        )
        return result.scalar_one()

    async def get_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> MessageTest:
        """Get a message test by ID with variants."""
        return await self._get_test_with_variants(test_id, workspace_id)

    async def update_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        data: MessageTestUpdate,
    ) -> MessageTest:
        """Update a message test."""
        message_test = await self._get_test(test_id, workspace_id)
        self._require_draft_or_paused(message_test, action="update")

        update_data = data.model_dump(exclude_unset=True)

        # Convert time strings to datetime.time objects
        if "sending_hours_start" in update_data:
            update_data["sending_hours_start"] = parse_time_string(
                update_data["sending_hours_start"]
            )
        if "sending_hours_end" in update_data:
            update_data["sending_hours_end"] = parse_time_string(
                update_data["sending_hours_end"]
            )

        for field, value in update_data.items():
            setattr(message_test, field, value)

        await self.db.commit()
        await self.db.refresh(message_test)

        return message_test

    async def delete_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        """Delete a message test."""
        message_test = await self._get_test(test_id, workspace_id)

        if message_test.status == "running":
            raise MessageTestValidationError(
                "Cannot delete running test. Pause it first."
            )

        await self.db.delete(message_test)
        await self.db.commit()

    # === Variant Management ===

    async def list_variants(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> list[TestVariantResponse]:
        """List variants for a message test."""
        await self._get_test(test_id, workspace_id)

        variants_result = await self.db.execute(
            select(TestVariant)
            .where(TestVariant.message_test_id == test_id)
            .order_by(TestVariant.sort_order)
        )
        variants = variants_result.scalars().all()

        return [TestVariantResponse.model_validate(v) for v in variants]

    async def create_variant(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        data: TestVariantCreate,
    ) -> TestVariant:
        """Create a new variant for a message test."""
        message_test = await self._get_test(test_id, workspace_id)
        self._require_draft_or_paused(message_test, action="add variants to")

        variant = TestVariant(
            message_test_id=test_id,
            **data.model_dump(),
        )
        self.db.add(variant)
        message_test.total_variants += 1

        await self.db.commit()
        await self.db.refresh(variant)

        return variant

    async def update_variant(
        self,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        data: TestVariantUpdate,
    ) -> TestVariant:
        """Update a variant."""
        message_test = await self._get_test(test_id, workspace_id)
        self._require_draft_or_paused(message_test, action="update variants on")

        result = await self.db.execute(
            select(TestVariant).where(
                TestVariant.id == variant_id,
                TestVariant.message_test_id == test_id,
            )
        )
        variant = result.scalar_one_or_none()

        if not variant:
            raise VariantNotFoundError()

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(variant, field, value)

        await self.db.commit()
        await self.db.refresh(variant)

        return variant

    async def delete_variant(
        self,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        """Delete a variant."""
        message_test = await self._get_test(test_id, workspace_id)
        self._require_draft_or_paused(message_test, action="delete variants from")

        result = await self.db.execute(
            select(TestVariant).where(
                TestVariant.id == variant_id,
                TestVariant.message_test_id == test_id,
            )
        )
        variant = result.scalar_one_or_none()

        if not variant:
            raise VariantNotFoundError()

        await self.db.delete(variant)
        message_test.total_variants -= 1
        await self.db.commit()

    # === Contact Management ===

    async def add_contacts(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        contacts_in: TestContactAdd,
    ) -> dict[str, int]:
        """Add contacts to a message test."""
        message_test = await self._get_test(test_id, workspace_id)
        self._require_draft_or_paused(message_test, action="add contacts to")

        # Verify contacts belong to workspace
        contacts_result = await self.db.execute(
            select(Contact).where(
                Contact.id.in_(contacts_in.contact_ids),
                Contact.workspace_id == workspace_id,
            )
        )
        valid_contacts = contacts_result.scalars().all()
        valid_contact_ids = {c.id for c in valid_contacts}

        # Get existing test contacts
        existing_result = await self.db.execute(
            select(TestContact.contact_id).where(
                TestContact.message_test_id == test_id
            )
        )
        existing_ids = {row[0] for row in existing_result.all()}

        # Add new contacts
        added_count = 0
        for contact_id in valid_contact_ids:
            if contact_id not in existing_ids:
                test_contact = TestContact(
                    message_test_id=test_id,
                    contact_id=contact_id,
                )
                self.db.add(test_contact)
                added_count += 1

        # Update test stats
        message_test.total_contacts += added_count
        await self.db.commit()

        return {"added": added_count}

    async def list_contacts(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        status_filter: str | None = None,
        limit: int = 100,
    ) -> list[TestContactResponse]:
        """List contacts in a message test."""
        await self._get_test(test_id, workspace_id)

        query = select(TestContact).where(TestContact.message_test_id == test_id)

        if status_filter:
            query = query.where(TestContact.status == status_filter)

        query = query.order_by(TestContact.created_at.desc()).limit(limit)

        contacts_result = await self.db.execute(query)
        contacts = contacts_result.scalars().all()

        return [TestContactResponse.model_validate(c) for c in contacts]

    # === Test Actions ===

    async def start_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, str]:
        """Start a message test."""
        message_test = await self._get_test(test_id, workspace_id)

        if message_test.status not in ("draft", "paused"):
            raise MessageTestValidationError(
                f"Cannot start test with status: {message_test.status}"
            )

        # Check if test has contacts
        contact_count_result = await self.db.execute(
            select(func.count(TestContact.id)).where(
                TestContact.message_test_id == test_id
            )
        )
        contact_count = contact_count_result.scalar() or 0

        if contact_count == 0:
            raise MessageTestValidationError("Test has no contacts")

        # Check if test has at least 2 variants
        variant_count_result = await self.db.execute(
            select(func.count(TestVariant.id)).where(
                TestVariant.message_test_id == test_id
            )
        )
        variant_count = variant_count_result.scalar() or 0

        if variant_count < 2:
            raise MessageTestValidationError("Test needs at least 2 variants")

        message_test.status = MessageTestStatus.RUNNING
        message_test.started_at = message_test.started_at or datetime.now(UTC)
        await self.db.commit()

        return {
            "status": "running",
            "message": f"Test started with {contact_count} contacts and {variant_count} variants",
        }

    async def pause_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, str]:
        """Pause a message test."""
        message_test = await self._get_test(test_id, workspace_id)

        if message_test.status != "running":
            raise MessageTestValidationError("Can only pause running tests")

        message_test.status = MessageTestStatus.PAUSED
        await self.db.commit()

        return {"status": "paused"}

    async def complete_test(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, str]:
        """Mark a message test as completed."""
        message_test = await self._get_test(test_id, workspace_id)

        if message_test.status not in ("running", "paused"):
            raise MessageTestValidationError(
                "Can only complete running or paused tests"
            )

        message_test.status = MessageTestStatus.COMPLETED
        message_test.completed_at = datetime.now(UTC)
        await self.db.commit()

        return {"status": "completed"}

    # === Analytics ===

    async def get_analytics(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> MessageTestAnalytics:
        """Get message test analytics."""
        message_test = await self._get_test_with_variants(test_id, workspace_id)

        # Calculate rates
        overall_response_rate = 0.0
        if message_test.messages_sent > 0:
            overall_response_rate = (
                message_test.replies_received / message_test.messages_sent
            ) * 100

        overall_qualification_rate = 0.0
        if message_test.replies_received > 0:
            overall_qualification_rate = (
                message_test.contacts_qualified / message_test.replies_received
            ) * 100

        # Build variant analytics
        variant_analytics = []
        for variant in sorted(message_test.variants, key=lambda v: v.sort_order):
            variant_analytics.append(
                VariantAnalytics(
                    variant_id=variant.id,
                    variant_name=variant.name,
                    is_control=variant.is_control,
                    contacts_assigned=variant.contacts_assigned,
                    messages_sent=variant.messages_sent,
                    replies_received=variant.replies_received,
                    contacts_qualified=variant.contacts_qualified,
                    response_rate=variant.response_rate,
                    qualification_rate=variant.qualification_rate,
                )
            )

        # Determine statistical significance
        has_enough_data = (
            all(v.messages_sent >= 30 for v in message_test.variants)
            if message_test.variants
            else False
        )

        return MessageTestAnalytics(
            test_id=message_test.id,
            test_name=message_test.name,
            status=message_test.status,
            total_contacts=message_test.total_contacts,
            total_variants=message_test.total_variants,
            messages_sent=message_test.messages_sent,
            replies_received=message_test.replies_received,
            contacts_qualified=message_test.contacts_qualified,
            overall_response_rate=overall_response_rate,
            overall_qualification_rate=overall_qualification_rate,
            variants=variant_analytics,
            winning_variant_id=message_test.winning_variant_id,
            statistical_significance=has_enough_data,
        )

    # === Winner Selection & Campaign Conversion ===

    async def select_winner(
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        variant_id: uuid.UUID,
    ) -> MessageTest:
        """Select a winning variant for the test."""
        message_test = await self._get_test(test_id, workspace_id)

        # Verify variant belongs to this test
        variant_result = await self.db.execute(
            select(TestVariant).where(
                TestVariant.id == variant_id,
                TestVariant.message_test_id == test_id,
            )
        )
        if not variant_result.scalar_one_or_none():
            raise VariantNotFoundError("Variant not found in this test")

        message_test.winning_variant_id = variant_id
        await self.db.commit()
        await self.db.refresh(message_test)

        return message_test

    async def convert_to_campaign(  # noqa: PLR0912
        self,
        test_id: uuid.UUID,
        workspace_id: uuid.UUID,
        request_data: ConvertToCampaignRequest,
    ) -> dict[str, str]:
        """Convert a message test to a full campaign."""
        message_test = await self._get_test_with_variants(test_id, workspace_id)

        # Determine which message to use
        initial_message = ""
        if request_data.use_winning_message and message_test.winning_variant_id:
            for variant in message_test.variants:
                if variant.id == message_test.winning_variant_id:
                    initial_message = variant.message_template
                    break
        elif message_test.variants:
            best_variant = max(message_test.variants, key=lambda v: v.response_rate)
            initial_message = best_variant.message_template

        if not initial_message:
            raise MessageTestValidationError(
                "No message template available for campaign"
            )

        # Create the campaign
        campaign = Campaign(
            workspace_id=workspace_id,
            agent_id=message_test.agent_id,
            name=request_data.campaign_name,
            description=f"Converted from message test: {message_test.name}",
            campaign_type="sms",
            status=CampaignStatus.DRAFT,
            from_phone_number=message_test.from_phone_number,
            use_number_pool=message_test.use_number_pool,
            initial_message=initial_message,
            ai_enabled=message_test.ai_enabled,
            qualification_criteria=message_test.qualification_criteria,
            sending_hours_start=message_test.sending_hours_start,
            sending_hours_end=message_test.sending_hours_end,
            sending_days=message_test.sending_days,
            timezone=message_test.timezone,
            messages_per_minute=message_test.messages_per_minute,
        )
        self.db.add(campaign)
        await self.db.flush()

        # Add remaining contacts if requested
        added_contacts = 0
        if request_data.include_remaining_contacts:
            remaining_contacts_result = await self.db.execute(
                select(TestContact).where(
                    TestContact.message_test_id == test_id,
                    TestContact.status == TestContactStatus.PENDING,
                )
            )
            remaining_contacts = remaining_contacts_result.scalars().all()

            for tc in remaining_contacts:
                campaign_contact = CampaignContact(
                    campaign_id=campaign.id,
                    contact_id=tc.contact_id,
                )
                self.db.add(campaign_contact)
                added_contacts += 1

            campaign.total_contacts = added_contacts

        # Link the campaign to the test
        message_test.converted_to_campaign_id = campaign.id

        await self.db.commit()

        return {
            "campaign_id": str(campaign.id),
            "message": f"Campaign created with {added_contacts} contacts",
        }
