"""Messenger/Instagram DM ingestion against a real database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.db.tenancy import mark_session_as_system
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.workspace import Workspace, WorkspaceIntegration
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
)
from app.services.lead_sources.meta_messenger_service import (
    MESSAGING_WINDOW,
    MetaMessageEvent,
    extract_phone,
    process_meta_message,
)

pytestmark = pytest.mark.integration


class WorkspaceFactory(Protocol):
    """Creates a committed workspace whose Meta integration owns ``page_id``."""

    async def __call__(
        self, db: AsyncSession, *, page_id: str
    ) -> tuple[Workspace, WorkspaceIntegration]: ...


TOKEN_KEY = "access_" + "token"


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Keep shared asyncpg connections on each test's event loop."""
    await engine.dispose()
    yield
    await engine.dispose()


class _FakeGraph:
    """Graph client stub that returns a profile name without any network I/O."""

    def __init__(self, name: str | None = "Dana Rivers", error: Exception | None = None) -> None:
        self.name = name
        self.error = error

    async def fetch_sender_name(self, *, psid: str, access_token: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.name


def _unique_page_id() -> str:
    """A fresh Page ID per test, so tests never contend for the same Page."""
    return f"page-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def make_workspace() -> AsyncIterator[WorkspaceFactory]:
    """Create committed workspaces, and delete them again afterwards.

    Committed rather than flushed because webhook routing deliberately resolves
    the owning workspace in its own session \u2014 an uncommitted fixture would be
    invisible to the code under test, exactly as it would be in production.
    """
    created: list[uuid.UUID] = []

    async def factory(db: AsyncSession, *, page_id: str) -> tuple[Workspace, WorkspaceIntegration]:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="DM Test",
            slug=f"dm-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        integration = WorkspaceIntegration(
            workspace_id=workspace.id,
            integration_type="meta_lead_ads",
            credentials={"page_id": page_id, TOKEN_KEY: "page-token"},
            is_active=True,
        )
        db.add(integration)
        await db.commit()
        await db.refresh(workspace)
        await db.refresh(integration)
        created.append(workspace.id)
        return workspace, integration

    yield factory

    async with AsyncSessionLocal() as cleanup:
        mark_session_as_system(cleanup, reason="test teardown across fixture workspaces")
        for workspace_id in created:
            workspace = await cleanup.get(Workspace, workspace_id)
            if workspace is not None:
                await cleanup.delete(workspace)
        await cleanup.commit()


def _event(
    page_id: str,
    *,
    psid: str = "1234567890123456",
    text: str = "do you do gutter cleaning?",
    message_id: str | None = None,
    channel: MessageChannel = MessageChannel.MESSENGER,
    sent_at_ms: int | None = None,
) -> MetaMessageEvent:
    """One inbound DM.

    ``psid`` is stable by default so repeated calls describe the same person,
    while ``message_id`` defaults to a fresh id so they are distinct deliveries
    — pass it explicitly to replay one, the way Meta retries.
    """
    return MetaMessageEvent(
        account_id=page_id,
        psid=psid,
        message_id=message_id or f"m_{uuid.uuid4().hex[:10]}",
        text=text,
        channel=channel,
        sent_at_ms=sent_at_ms,
    )


async def test_first_dm_opens_a_contactless_thread_inside_the_window(
    make_workspace: WorkspaceFactory,
) -> None:
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)
        sent_at_ms = int(datetime(2026, 8, 30, 12, 0, tzinfo=UTC).timestamp() * 1000)

        created = await process_meta_message(
            db,
            event=_event(page_id, sent_at_ms=sent_at_ms),
            client=_FakeGraph(),
        )
        assert created is True

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        # No phone was shared, so there is nothing to link a contact on.
        assert conversation.contact_id is None
        assert conversation.contact_phone is None
        assert conversation.workspace_phone is None
        assert conversation.messenger_psid is not None
        assert conversation.messenger_display_name == "Dana Rivers"
        assert conversation.channel == MessageChannel.MESSENGER
        assert (
            conversation.messenger_window_expires_at
            == datetime(2026, 8, 30, 12, 0, tzinfo=UTC) + MESSAGING_WINDOW
        )


async def test_replayed_delivery_does_not_duplicate_the_message(
    make_workspace: WorkspaceFactory,
) -> None:
    """Meta retries with the same ``mid``; the second one must be a no-op."""
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)
        event = _event(page_id)

        assert await process_meta_message(db, event=event, client=_FakeGraph()) is True
        assert await process_meta_message(db, event=event, client=_FakeGraph()) is False

        message_count = (
            await db.execute(
                select(func.count(Message.id))
                .join(Conversation)
                .where(Conversation.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert message_count == 1


async def test_a_second_dm_reuses_the_thread_and_extends_the_window(
    make_workspace: WorkspaceFactory,
) -> None:
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)
        first = int(datetime(2026, 8, 30, 12, 0, tzinfo=UTC).timestamp() * 1000)
        later = int(datetime(2026, 8, 30, 20, 0, tzinfo=UTC).timestamp() * 1000)

        await process_meta_message(db, event=_event(page_id, sent_at_ms=first), client=_FakeGraph())
        await process_meta_message(db, event=_event(page_id, sent_at_ms=later), client=_FakeGraph())

        conversations = (
            (
                await db.execute(
                    select(Conversation).where(Conversation.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(conversations) == 1
        assert (
            conversations[0].messenger_window_expires_at
            == datetime(2026, 8, 30, 20, 0, tzinfo=UTC) + MESSAGING_WINDOW
        )


async def test_a_page_no_workspace_owns_is_rejected(make_workspace: WorkspaceFactory) -> None:
    async with AsyncSessionLocal() as db:
        await make_workspace(db, page_id=_unique_page_id())
        with pytest.raises(MetaLeadAdsValidationError):
            await process_meta_message(
                db,
                event=_event(f"page-owned-by-nobody-{uuid.uuid4().hex[:8]}"),
                client=_FakeGraph(),
            )


async def test_a_page_claimed_by_two_workspaces_is_refused_not_guessed(
    make_workspace: WorkspaceFactory,
) -> None:
    """Guessing would deliver a stranger's DM into another tenant's inbox."""
    async with AsyncSessionLocal() as db:
        shared = _unique_page_id()
        await make_workspace(db, page_id=shared)
        await make_workspace(db, page_id=shared)
        await db.commit()

        with pytest.raises(MetaLeadAdsError):
            await process_meta_message(
                db,
                event=_event(shared),
                client=_FakeGraph(),
            )


async def test_an_inactive_integration_does_not_receive_dms(
    make_workspace: WorkspaceFactory,
) -> None:
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        _, integration = await make_workspace(db, page_id=page_id)
        integration.is_active = False
        await db.commit()

        with pytest.raises(MetaLeadAdsValidationError):
            await process_meta_message(db, event=_event(page_id), client=_FakeGraph())


async def test_a_missing_profile_name_does_not_cost_us_the_message(
    make_workspace: WorkspaceFactory,
) -> None:
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)
        graph = _FakeGraph(error=MetaLeadAdsError("profile forbidden"))

        assert await process_meta_message(db, event=_event(page_id), client=graph) is True

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        assert conversation.messenger_display_name is None


async def test_sharing_a_phone_links_a_contact_attributed_to_facebook_ads(
    make_workspace: WorkspaceFactory,
) -> None:
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)

        await process_meta_message(db, event=_event(page_id), client=_FakeGraph())
        await process_meta_message(
            db,
            event=_event(page_id, text="sure, my number is (415) 555-0132"),
            client=_FakeGraph(),
        )

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        assert conversation.contact_id is not None

        contact = await db.get(Contact, conversation.contact_id)
        assert contact is not None
        assert contact.phone_number == "+14155550132"
        assert contact.first_name == "Dana"

        # The whole point of linking: the DM now feeds the Lead Source ROI card.
        assert contact.first_touch_lead_source_id is not None
        source = await db.get(LeadSource, contact.first_touch_lead_source_id)
        assert source is not None
        assert source.source_type == LeadSourceType.FACEBOOK_ADS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call me at (415) 555-0132", "+14155550132"),
        ("my cell is 415-555-0132 thanks", "+14155550132"),
        ("call me at 5pm on the 15th", None),
        ("order #12345678 please", None),
        ("", None),
    ],
)
def test_extract_phone_only_matches_real_numbers(text: str, expected: str | None) -> None:
    assert extract_phone(text) == expected


async def test_window_expiry_is_measured_from_the_users_message_not_now(
    make_workspace: WorkspaceFactory,
) -> None:
    """A delayed webhook must not grant a fresh 24 hours."""
    async with AsyncSessionLocal() as db:
        page_id = _unique_page_id()
        workspace, _ = await make_workspace(db, page_id=page_id)
        long_ago = datetime.now(UTC) - timedelta(hours=30)

        await process_meta_message(
            db,
            event=_event(page_id, sent_at_ms=int(long_ago.timestamp() * 1000)),
            client=_FakeGraph(),
        )

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        assert conversation.messenger_window_expires_at is not None
        assert conversation.messenger_window_expires_at < datetime.now(UTC)
