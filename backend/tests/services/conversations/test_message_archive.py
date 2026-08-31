"""PostgreSQL coverage for the message archive: thread search and history paging.

Both behaviours here are the difference between an archive an operator can trust
and one that quietly damages state while they browse, so they are exercised
against a real database rather than a mocked session.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.models.workspace import Workspace
from app.services.conversations.conversation_service import ConversationService

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id() -> AsyncIterator[uuid.UUID]:
    value = uuid.uuid4()
    yield value
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == value))
        await db.commit()


async def _workspace(db, workspace_id: uuid.UUID) -> None:
    db.add(
        Workspace(
            id=workspace_id,
            name="Archive",
            slug=f"archive-{uuid.uuid4().hex[:8]}",
            settings={"timezone": "America/New_York"},
        )
    )
    await db.flush()


async def _thread(
    db,
    workspace_id: uuid.UUID,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    unread: int = 0,
) -> Conversation:
    contact = Contact(
        workspace_id=workspace_id,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=f"{first_name.lower()}@example.com",
        status="new",
    )
    db.add(contact)
    await db.flush()
    conversation = Conversation(
        workspace_id=workspace_id,
        contact_id=contact.id,
        workspace_phone="+15125550999",
        contact_phone=phone,
        channel=MessageChannel.SMS.value,
        unread_count=unread,
        last_message_at=datetime.now(UTC),
    )
    db.add(conversation)
    await db.flush()
    return conversation


class TestThreadSearch:
    """Operators find an old thread by the person's name, not by scrolling."""

    async def test_matches_first_or_last_name_and_excludes_everyone_else(
        self, workspace_id
    ) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            await _thread(
                db,
                workspace_id,
                first_name="Marguerite",
                last_name="Alvarez",
                phone="+15125550101",
            )
            await _thread(
                db, workspace_id, first_name="Dwight", last_name="Boone", phone="+15125550102"
            )
            await db.commit()
            svc = ConversationService(db)

            by_first = await svc.list_conversations(workspace_id=workspace_id, search="marguer")
            by_last = await svc.list_conversations(workspace_id=workspace_id, search="boone")
            unmatched = await svc.list_conversations(workspace_id=workspace_id, search="zzzz")
            unfiltered = await svc.list_conversations(workspace_id=workspace_id)

            # Case-insensitive partial match on either name part.
            assert [c.contact_name for c in by_first.items] == ["Marguerite Alvarez"]
            assert [c.contact_name for c in by_last.items] == ["Dwight Boone"]
            # `total` drives the pager, so it must reflect the filter, not the
            # whole workspace -- otherwise the UI offers pages that do not exist.
            assert by_first.total == 1
            assert unmatched.items == []
            assert unmatched.total == 0
            assert unfiltered.total == 2


class TestMessageHistoryPaging:
    """Reading history must not damage the state an operator is looking at."""

    async def test_paging_reaches_old_messages_without_marking_the_thread_read(
        self, workspace_id
    ) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            conversation = await _thread(
                db,
                workspace_id,
                first_name="Perry",
                last_name="Nakamura",
                phone="+15125550103",
                unread=4,
            )
            start = datetime.now(UTC) - timedelta(days=900)
            for index in range(12):
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        direction=MessageDirection.INBOUND.value,
                        channel=MessageChannel.SMS.value,
                        status=MessageStatus.RECEIVED.value,
                        body=f"message {index}",
                        created_at=start + timedelta(days=index),
                    )
                )
            await db.commit()
            svc = ConversationService(db)

            newest = await svc.list_messages(
                conversation_id=conversation.id, workspace_id=workspace_id, page=1, page_size=5
            )
            oldest = await svc.list_messages(
                conversation_id=conversation.id, workspace_id=workspace_id, page=3, page_size=5
            )

            # Page 1 is the newest slice, page 3 reaches the very first message:
            # history older than one page is what "a long time ago" means.
            assert [m.body for m in newest.items] == [
                "message 7",
                "message 8",
                "message 9",
                "message 10",
                "message 11",
            ]
            assert [m.body for m in oldest.items] == ["message 0", "message 1"]
            assert newest.total == 12
            assert newest.pages == 3

            # The whole point of the separate endpoint: browsing an archive must
            # not clear a badge nobody actually read.
            await db.refresh(conversation)
            assert conversation.unread_count == 4

    async def test_another_workspaces_thread_is_not_readable(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            conversation = await _thread(
                db, workspace_id, first_name="Ines", last_name="Kovac", phone="+15125550104"
            )
            await db.commit()
            svc = ConversationService(db)

            # Same thread id, someone else's workspace: messages are PII, so this
            # must 404 rather than return a page.
            with pytest.raises(Exception) as excinfo:
                await svc.list_messages(
                    conversation_id=conversation.id, workspace_id=uuid.uuid4()
                )

            assert getattr(excinfo.value, "status_code", None) == 404
