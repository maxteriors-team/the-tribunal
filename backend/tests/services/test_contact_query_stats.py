"""Integration tests for contact stats + the new list sort keys.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: :meth:`ContactQueryService.get_stats` window counts + change
formatting, and the ``name_asc`` / ``last_activity_desc`` orderings added to
``list_contacts_paginated``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.workspace import Workspace
from app.services.contacts.contact_repository import list_contacts_paginated
from app.services.contacts.query_service import ContactQueryService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Stats", slug=f"stats-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(
    db,
    workspace_id: uuid.UUID,
    *,
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    status: str = "new",
    created_at: datetime | None = None,
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status=status,
    )
    if created_at is not None:
        contact.created_at = created_at
    db.add(contact)
    await db.flush()
    return contact


async def _conversation(
    db,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    last_message_at: datetime | None,
) -> Conversation:
    conv = Conversation(
        workspace_id=workspace_id,
        contact_id=contact_id,
        workspace_phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
        contact_phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
        channel="sms",
        last_message_at=last_message_at,
    )
    db.add(conv)
    await db.flush()
    return conv


async def test_get_stats_counts_windows_and_formats_change() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        # Current 30d window: 4 new leads (any status), 2 of them converted
        # "clients". "New leads" counts every contact created in the window.
        await _contact(db, ws.id, status="new", created_at=now - timedelta(days=5))
        await _contact(db, ws.id, status="contacted", created_at=now - timedelta(days=10))
        await _contact(db, ws.id, status="converted", created_at=now - timedelta(days=3))
        await _contact(db, ws.id, status="converted", created_at=now - timedelta(days=20))

        # Prior 30d window (30-60d ago): 2 leads, 1 converted.
        await _contact(db, ws.id, status="new", created_at=now - timedelta(days=40))
        await _contact(db, ws.id, status="converted", created_at=now - timedelta(days=50))

        # Earlier this year but outside the trailing windows: YTD-only converted.
        jan = datetime(now.year, 1, 1, tzinfo=UTC) + timedelta(days=1)
        if jan < now - timedelta(days=60):
            await _contact(db, ws.id, status="converted", created_at=jan)
            expected_ytd = 4  # 2 (30d) + 1 (prev) + 1 (jan)
        else:
            expected_ytd = 3  # jan would fall inside the trailing windows

        stats = await ContactQueryService(db).get_stats(workspace_id=ws.id)

    assert stats["new_leads_30d"] == 4
    assert stats["new_clients_30d"] == 2
    # 4 leads now vs 2 prior -> +100%; 2 clients now vs 1 prior -> +100%.
    assert stats["new_leads_change"] == "+100%"
    assert stats["new_clients_change"] == "+100%"
    assert stats["total_new_clients_ytd"] == expected_ytd


async def test_get_stats_empty_workspace_is_zeroed() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        stats = await ContactQueryService(db).get_stats(workspace_id=ws.id)

    assert stats == {
        "new_leads_30d": 0,
        "new_leads_change": "+0%",
        "new_clients_30d": 0,
        "new_clients_change": "+0%",
        "total_new_clients_ytd": 0,
    }


async def test_list_contacts_name_asc_orders_alphabetically() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _contact(db, ws.id, first_name="Charlie", last_name="Zeta")
        await _contact(db, ws.id, first_name="Alice", last_name="Young")
        await _contact(db, ws.id, first_name="Bob", last_name="Xray")

        rows, total = await list_contacts_paginated(workspace_id=ws.id, db=db, sort_by="name_asc")

    assert total == 3
    assert [row[0].first_name for row in rows] == ["Alice", "Bob", "Charlie"]


async def test_list_contacts_last_activity_desc_orders_by_recent_message() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        oldest = await _contact(db, ws.id, first_name="Oldest")
        newest = await _contact(db, ws.id, first_name="Newest")
        # `Silent` has no conversation -> null activity -> must sort last.
        await _contact(db, ws.id, first_name="Silent")

        await _conversation(db, ws.id, oldest.id, last_message_at=now - timedelta(days=10))
        await _conversation(db, ws.id, newest.id, last_message_at=now - timedelta(hours=1))
        # `silent` has no conversation -> null activity -> sorts last.

        rows, total = await list_contacts_paginated(
            workspace_id=ws.id, db=db, sort_by="last_activity_desc"
        )

    assert total == 3
    order = [row[0].first_name for row in rows]
    assert order[0] == "Newest"
    assert order[1] == "Oldest"
    assert order[2] == "Silent"
