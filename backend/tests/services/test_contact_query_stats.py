"""Integration tests for contact stats + the new list sort keys.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: :meth:`ContactQueryService.get_stats` window counts + change
formatting, and the ``name_asc`` / ``last_activity_desc`` orderings added to
``list_contacts_paginated``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.schemas.contact import ContactStatsResponse
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

    parsed = ContactStatsResponse.model_validate(stats)
    assert parsed.new_leads_30d == 0
    assert parsed.new_clients_30d == 0
    assert parsed.total_new_clients_ytd == 0
    assert parsed.new_leads_change is None
    assert parsed.new_clients_change is None
    assert parsed.client_metric_basis == "creation_cohort_current_status"


async def test_old_lead_converted_now_is_not_misreported_as_a_recent_creation() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        old = await _contact(db, ws.id, created_at=now - timedelta(days=75))
        old.status = "converted"
        await db.flush()

        stats = await ContactQueryService(db).get_stats(workspace_id=ws.id)
        assert stats["client_metric_basis"] == "creation_cohort_current_status"
        # A conversion-time report would count this event. We cannot produce one;
        # the explicitly labelled CREATION cohort must not silently substitute it.
        assert stats["new_clients_30d"] == 0
        assert stats["new_clients_change"] is None

        recent = await _contact(db, ws.id, status="converted", created_at=now - timedelta(days=5))
        for status, expected in [("converted", 1), ("lost", 0), ("converted", 1)]:
            recent.status = status
            await db.flush()
            stats = await ContactQueryService(db).get_stats(workspace_id=ws.id)
            assert stats["new_clients_30d"] == expected
            assert stats["new_clients_change"] is None

        # Drill-down uses the exact returned half-open creation bounds.
        cohort = await ContactQueryService(db).list_contacts(
            workspace_id=ws.id,
            filters=json.dumps(
                {
                    "logic": "and",
                    "rules": [
                        {
                            "field": "created_at",
                            "operator": "gte",
                            "value": stats["period_start"].isoformat(),
                        },
                        {
                            "field": "created_at",
                            "operator": "lt",
                            "value": stats["period_end"].isoformat(),
                        },
                        {"field": "status", "operator": "equals", "value": "converted"},
                    ],
                }
            ),
        )
        assert cohort["total"] == stats["new_clients_30d"] == 1
        assert [item.id for item in cohort["items"]] == [recent.id]


async def test_stats_half_open_windows_and_workspace_local_year() -> None:
    now = datetime(2026, 9, 10, 12, tzinfo=UTC)
    year_start = datetime(2025, 12, 31, 11, tzinfo=UTC)  # Auckland Jan 1
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        ws.settings = {"timezone": "Pacific/Auckland"}
        for created in [
            year_start - timedelta(microseconds=1),
            year_start,
            now - timedelta(days=60),
            now - timedelta(days=30),
            now - timedelta(microseconds=1),
            now,
            now + timedelta(days=1),
        ]:
            await _contact(db, ws.id, status="converted", created_at=created)
        other = await _workspace(db)
        await _contact(db, other.id, status="converted", created_at=now - timedelta(days=1))

        with patch("app.services.contacts.query_service.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            stats = await ContactQueryService(db).get_stats(workspace_id=ws.id)

        assert stats["period_start"] == now - timedelta(days=30)
        assert stats["period_end"] == now
        assert stats["year_start"] == year_start
        assert stats["timezone"] == "Pacific/Auckland"
        assert stats["new_leads_30d"] == stats["new_clients_30d"] == 2
        assert stats["new_leads_change"] == stats["new_clients_change"] == "+100%"
        assert stats["total_new_clients_ytd"] == 4


async def test_status_facets_include_off_page_contact_and_ignore_selected_status() -> None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        qualified = await _contact(
            db, ws.id, status="qualified", created_at=now - timedelta(days=75)
        )
        for _ in range(100):
            await _contact(db, ws.id, created_at=now - timedelta(days=1))
        other = await _workspace(db)
        await _contact(db, other.id, status="qualified")
        service = ContactQueryService(db)
        expected = {
            "all": 101,
            "new": 100,
            "contacted": 0,
            "qualified": 1,
            "converted": 0,
            "lost": 0,
        }

        first = await service.list_contacts(workspace_id=ws.id, page_size=100)
        assert len(first["items"]) == 100
        assert all(item.status == "new" for item in first["items"])
        assert first["status_counts"] == expected
        second = await service.list_contacts(workspace_id=ws.id, page=2, page_size=100)
        assert [item.id for item in second["items"]] == [qualified.id]
        assert second["status_counts"] == expected
        selected = await service.list_contacts(workspace_id=ws.id, status_filter="qualified")
        assert selected["total"] == 1
        assert selected["status_counts"] == expected
        empty_page = await service.list_contacts(workspace_id=ws.id, page=100, page_size=10)
        assert empty_page["items"] == []
        assert empty_page["status_counts"] == expected


async def test_status_facets_share_search_tags_and_advanced_filter_scope() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        tags = [Tag(workspace_id=ws.id, name=name) for name in ("A", "B")]
        db.add_all(tags)
        await db.flush()
        for name, status, source, company, tagged in [
            ("Match", "new", "site", "Good", True),
            ("Match", "qualified", "site", "Good", True),
            ("Different", "qualified", "site", "Good", True),
            ("Match", "qualified", "other", "Good", True),
            ("Match", "qualified", "site", "Excluded", True),
            ("Match", "qualified", "site", "Good", False),
        ]:
            contact = await _contact(db, ws.id, first_name=name, status=status)
            contact.source = source
            contact.company_name = company
            if tagged:
                db.add_all([ContactTag(contact_id=contact.id, tag_id=tag.id) for tag in tags])
        await db.flush()
        result = await ContactQueryService(db).list_contacts(
            workspace_id=ws.id,
            search="Match",
            source="site",
            tags=",".join(str(tag.id) for tag in tags),
            filters=json.dumps(
                {
                    "logic": "and",
                    "rules": [
                        {"field": "company_name", "operator": "equals", "value": "Good"},
                    ],
                }
            ),
            status_filter="qualified",
        )
        assert result["total"] == 1
        assert result["status_counts"] == {
            "all": 2,
            "new": 1,
            "contacted": 0,
            "qualified": 1,
            "converted": 0,
            "lost": 0,
        }
        empty = await ContactQueryService(db).list_contacts(workspace_id=ws.id, search="Absent")
        assert empty["status_counts"] == dict.fromkeys(result["status_counts"], 0)


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
