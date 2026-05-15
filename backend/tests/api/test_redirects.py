"""Tests for the public short-link redirect endpoint.

Covers :mod:`app.api.redirects`:

* 404 when the short code is unknown.
* Happy-path redirect: 302 to ``target_url``, a ``LinkClick`` row is added,
  the ``ShortLink`` click counters are bumped, and the request metadata
  (IP, user-agent, referer) is recorded on the click.
* Campaign-attributed link: ``Campaign.links_clicked`` is also incremented.
* Standalone link (no ``campaign_id``): campaign update is *not* issued.

All tests stub out the database via ``app.dependency_overrides[get_db]``
so they run without Postgres. We inspect the recorded statements to verify
the SQL the endpoint emits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table
from sqlalchemy.sql.dml import Update

from app.api.redirects import router as redirects_router
from app.db.session import get_db
from app.models.campaign import Campaign
from app.models.link_click import LinkClick
from app.models.short_link import ShortLink

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _update_target_name(stmt: Update) -> str:
    """Return the table name targeted by an UPDATE statement.

    ``stmt.table`` is typed as ``TableClause | Alias | Join``; in our app it's
    always a concrete ``Table`` so we narrow with an assertion.
    """
    table = stmt.table
    assert isinstance(table, Table)
    return table.name


def _make_short_link(*, campaign_id: uuid.UUID | None = None) -> MagicMock:
    """Build a minimal :class:`ShortLink` mock for redirect tests."""
    link = MagicMock(spec=ShortLink)
    link.id = uuid.uuid4()
    link.short_code = "abc123"
    link.target_url = "https://example.com/landing"
    link.campaign_id = campaign_id
    link.click_count = 4
    return link


def _make_db_returning(
    short_link: ShortLink | None,
) -> tuple[AsyncMock, list[Any]]:
    """Build an :class:`AsyncSession` mock whose first SELECT returns ``short_link``.

    Returns the mock plus a list that captures every statement passed to
    ``db.execute`` in order, so tests can assert on which UPDATEs ran.
    """
    captured: list[Any] = []

    select_result = MagicMock()
    select_result.scalar_one_or_none = MagicMock(return_value=short_link)

    update_result = MagicMock()
    update_result.rowcount = 1

    async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        captured.append(stmt)
        # The first call is the SELECT; everything after is an UPDATE.
        if len(captured) == 1:
            return select_result
        return update_result

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db, captured


def _make_app(db: AsyncMock) -> FastAPI:
    """Mount the redirects router with ``get_db`` stubbed to ``db``."""
    app = FastAPI(lifespan=_test_lifespan)

    async def _override_db() -> AsyncIterator[AsyncMock]:
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.include_router(redirects_router)
    return app


@pytest.fixture
def short_link() -> MagicMock:
    return _make_short_link()


# --------------------------------------------------------------------------- #
# 404 — unknown short code
# --------------------------------------------------------------------------- #


async def test_unknown_short_code_returns_404() -> None:
    db, _captured = _make_db_returning(None)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/r/nope")

    assert response.status_code == 404
    # Only the SELECT ran — no click row inserted, no commit.
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Happy path — 302 redirect, click logged, counters bumped
# --------------------------------------------------------------------------- #


async def test_known_code_redirects_with_302(short_link: MagicMock) -> None:
    db, _captured = _make_db_returning(short_link)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # follow_redirects=False so we can inspect the 302 directly.
        response = await client.get(
            "/r/abc123",
            follow_redirects=False,
            headers={"User-Agent": "test-agent", "Referer": "https://search.example"},
        )

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/landing"


async def test_click_row_added_with_request_metadata(
    short_link: MagicMock,
) -> None:
    db, _captured = _make_db_returning(short_link)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get(
            "/r/abc123",
            follow_redirects=False,
            headers={"User-Agent": "test-agent", "Referer": "https://ref.example"},
        )

    # Exactly one row added — the click record.
    db.add.assert_called_once()
    click_arg = db.add.call_args.args[0]
    assert isinstance(click_arg, LinkClick)
    assert click_arg.short_link_id == short_link.id
    assert click_arg.user_agent == "test-agent"
    assert click_arg.referer == "https://ref.example"
    # The mock ASGI client sets ``request.client`` so we should record an IP.
    assert click_arg.ip_address is not None
    # ``clicked_at`` is timezone-aware (UTC).
    assert click_arg.clicked_at.tzinfo is not None

    db.commit.assert_awaited_once()


async def test_short_link_click_counter_is_bumped(
    short_link: MagicMock,
) -> None:
    db, captured = _make_db_returning(short_link)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/r/abc123", follow_redirects=False)

    # SELECT (short link) + UPDATE (short link counters) = 2 statements
    # when there's no campaign.
    assert len(captured) == 2
    # Second statement must be an UPDATE targeting ShortLink.
    update_stmt = captured[1]
    assert isinstance(update_stmt, Update)
    assert _update_target_name(update_stmt) == ShortLink.__tablename__


# --------------------------------------------------------------------------- #
# Campaign attribution
# --------------------------------------------------------------------------- #


async def test_campaign_counter_bumped_when_attributed() -> None:
    campaign_id = uuid.uuid4()
    short_link = _make_short_link(campaign_id=campaign_id)
    db, captured = _make_db_returning(short_link)
    app = _make_app(db)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/r/abc123", follow_redirects=False)

    # SELECT short link + UPDATE short link + UPDATE campaign = 3 statements.
    assert len(captured) == 3
    update_targets = [
        _update_target_name(stmt)
        for stmt in captured[1:]
        if isinstance(stmt, Update)
    ]
    assert ShortLink.__tablename__ in update_targets
    assert Campaign.__tablename__ in update_targets


async def test_no_campaign_update_for_standalone_link(
    short_link: MagicMock,
) -> None:
    """``short_link.campaign_id is None`` → no UPDATE on the campaigns table."""
    db, captured = _make_db_returning(short_link)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.get("/r/abc123", follow_redirects=False)

    update_targets = [
        _update_target_name(stmt)
        for stmt in captured[1:]
        if isinstance(stmt, Update)
    ]
    assert Campaign.__tablename__ not in update_targets


# --------------------------------------------------------------------------- #
# Missing optional headers
# --------------------------------------------------------------------------- #


async def test_missing_user_agent_and_referer_are_tolerated(
    short_link: MagicMock,
) -> None:
    """Clients without UA or Referer headers still redirect cleanly."""
    db, _captured = _make_db_returning(short_link)
    app = _make_app(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # httpx adds a default user-agent; strip it explicitly so we can test
        # the None-tolerant code path on the server.
        response = await client.get(
            "/r/abc123",
            follow_redirects=False,
            headers={"User-Agent": ""},
        )
    assert response.status_code == 302
    click_arg = db.add.call_args.args[0]
    # ``Referer`` was never sent, so the recorded value should be None.
    assert click_arg.referer is None
