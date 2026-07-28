"""Tenant-isolation tests for the phone-number read routes.

The list/get handlers once skipped the ``workspace_id`` predicate on the claim
that phone numbers were "shared across workspaces" — they are not:
``phone_numbers.workspace_id`` is non-nullable and every write path already
scopes by it. These drive the handlers against a real DB (marked
``integration``; run with ``-m integration``) so the SQL predicate itself is
under test, which a mocked session would not cover.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.phone_numbers import get_phone_number, list_phone_numbers
from app.db.session import AsyncSessionLocal, engine
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Phones Co", slug=f"pho-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _make_number(db: AsyncSession, workspace_id: uuid.UUID) -> PhoneNumber:
    number = PhoneNumber(
        workspace_id=workspace_id,
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(number)
    await db.flush()
    return number


# The handlers take ``current_user``/``membership`` purely as auth gates and
# never read them; the tenancy predicate is what these tests exercise.
_ANY = cast(Any, None)


async def test_list_returns_only_the_callers_workspace_numbers() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        mine = await _make_number(db, ws_a.id)
        theirs = await _make_number(db, ws_b.id)

        # page/page_size are passed explicitly: calling the handler directly
        # bypasses FastAPI's resolution of their ``Query(...)`` defaults.
        page = await list_phone_numbers(ws_a.id, _ANY, db, _ANY, page=1, page_size=100)

        returned = {item.id for item in page.items}
        assert mine.id in returned
        assert theirs.id not in returned


async def test_get_rejects_another_workspaces_number() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        theirs = await _make_number(db, ws_b.id)

        with pytest.raises(HTTPException) as exc:
            await get_phone_number(ws_a.id, theirs.id, _ANY, db, _ANY)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Phone number not found"


async def test_get_returns_an_owned_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        mine = await _make_number(db, ws.id)

        found = await get_phone_number(ws.id, mine.id, _ANY, db, _ANY)

        assert found.id == mine.id
