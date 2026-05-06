"""Tests for Resend webhook handler idempotency.

Verifies that retried webhook deliveries (same ``svix-id``) do not create
duplicate ``EmailEvent`` rows nor double-increment campaign counters.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.webhooks.resend_handlers import handle_event


def _make_event(event_type: str = "email.delivered") -> dict[str, Any]:
    return {
        "type": event_type,
        "created_at": "2026-05-06T12:00:00Z",
        "data": {
            "email_id": "msg_abc123",
            "id": "msg_abc123",
        },
    }


def _make_db_with_existing_event_id() -> MagicMock:
    """AsyncSession mock where the dedupe SELECT returns a hit."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_db_with_no_existing_event() -> MagicMock:
    """AsyncSession mock where dedupe SELECT misses and message lookup also misses."""
    db = MagicMock()
    miss = MagicMock()
    miss.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=miss)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_duplicate_svix_id_short_circuits_before_inserting() -> None:
    db = _make_db_with_existing_event_id()
    log = MagicMock()

    await handle_event(
        db,
        _make_event("email.delivered"),
        log=log,
        provider_event_id="evt_already_processed",
    )

    # Did the dedupe lookup, did NOT add a new row, did NOT commit, did NOT
    # try to find the message.
    db.execute.assert_awaited_once()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    log.info.assert_called_with(
        "resend_event_duplicate_skipped",
        event_type="email.delivered",
        provider_event_id="evt_already_processed",
    )


@pytest.mark.asyncio
async def test_unhandled_event_type_returns_without_dedupe_query() -> None:
    db = _make_db_with_no_existing_event()
    log = MagicMock()

    await handle_event(
        db,
        {"type": "email.something_unmapped", "data": {}},
        log=log,
        provider_event_id="evt_x",
    )

    db.execute.assert_not_called()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_provider_event_id_skips_dedupe_check() -> None:
    """If svix-id is missing we still process (best-effort) without dedupe."""
    db = _make_db_with_no_existing_event()
    log = MagicMock()

    await handle_event(
        db,
        _make_event("email.delivered"),
        log=log,
        provider_event_id=None,
    )

    # Only the message-lookup SELECT should fire (not a dedupe SELECT).
    assert db.execute.await_count == 1
    # Message lookup misses → workspace_id is None → early return, no insert.
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
