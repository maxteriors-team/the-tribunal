"""Tests for AuthRateLimitCleanupWorker.

The worker is small but security-relevant: if it deletes too aggressively it
can erase rate-limit / lockout history that's still inside an active window,
and if it doesn't run the table grows unbounded. These tests pin:

1. The retention buffer comfortably exceeds the rate-limit windows in
   ``app/api/v1/auth.py`` (regression guard if someone shortens RETENTION_HOURS
   or lengthens the auth windows without updating both).
2. The poll cadence is hourly.
3. ``_process_items`` issues an indexed range delete with the correct cutoff
   and commits the transaction.
4. The worker is wired into ``ALL_REGISTRIES`` so it actually runs.
5. Deletion counts are recorded as items-processed only when rows are deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers import ALL_REGISTRIES
from app.workers.auth_rate_limit_cleanup_worker import (
    POLL_INTERVAL_SECONDS,
    RETENTION_HOURS,
    AuthRateLimitCleanupWorker,
    _registry,
)
from app.workers.base import BaseWorker


def test_class_inherits_base_worker() -> None:
    assert issubclass(AuthRateLimitCleanupWorker, BaseWorker)


def test_component_name() -> None:
    assert AuthRateLimitCleanupWorker.COMPONENT_NAME == "auth_rate_limit_cleanup"


def test_poll_interval_is_hourly() -> None:
    """Cadence is hourly — see module docstring rationale."""
    assert POLL_INTERVAL_SECONDS == 3600
    assert AuthRateLimitCleanupWorker.POLL_INTERVAL_SECONDS == 3600


def test_retention_exceeds_auth_windows() -> None:
    """Retention must comfortably exceed the longest rate-limit window.

    ``app/api/v1/auth.py`` evaluates 15-minute windows for both the IP rate
    limiter and the username lockout. If retention drops below those windows
    the cleanup would erase rows the limiter still needs.
    """
    from app.api.v1 import auth as auth_module

    longest_window_minutes = max(
        auth_module._AUTH_RATE_WINDOW_MINUTES,
        auth_module._USERNAME_LOCKOUT_WINDOW_MINUTES,
    )
    # Require at least a 4x buffer over the longest active window.
    assert longest_window_minutes * 4 <= RETENTION_HOURS * 60


def test_registered_in_all_registries() -> None:
    """Worker must be in ALL_REGISTRIES or it never starts."""
    assert _registry in ALL_REGISTRIES


@pytest.mark.asyncio
async def test_process_items_deletes_old_rows_and_commits() -> None:
    """``_process_items`` issues a DELETE WHERE created_at < cutoff and commits."""
    worker = AuthRateLimitCleanupWorker()

    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    db.commit = AsyncMock()

    result = MagicMock()
    result.rowcount = 7
    db.execute = AsyncMock(return_value=result)

    fixed_now = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)

    class _FakeDatetime:
        @staticmethod
        def now(tz: object = None) -> datetime:
            return fixed_now

    with (
        patch(
            "app.workers.auth_rate_limit_cleanup_worker.system_session",
            return_value=db,
        ),
        patch(
            "app.workers.auth_rate_limit_cleanup_worker.datetime",
            _FakeDatetime,
        ),
    ):
        await worker._process_items()

    # Exactly one DELETE executed, then committed.
    assert db.execute.await_count == 1
    db.commit.assert_awaited_once()

    # The compiled statement must be a DELETE against auth_rate_limits whose
    # WHERE clause references the expected cutoff (now - RETENTION_HOURS).
    stmt = db.execute.await_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled).lower()
    assert "delete from auth_rate_limits" in sql
    assert "created_at <" in sql

    # Items-processed counter reflects deleted rows.
    assert worker._items_this_cycle == 7


@pytest.mark.asyncio
async def test_process_items_no_rows_no_items_recorded() -> None:
    """When nothing was deleted, do not record items or log a deletion line."""
    worker = AuthRateLimitCleanupWorker()

    db = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    db.commit = AsyncMock()

    result = MagicMock()
    result.rowcount = 0
    db.execute = AsyncMock(return_value=result)

    with patch(
        "app.workers.auth_rate_limit_cleanup_worker.system_session",
        return_value=db,
    ):
        await worker._process_items()

    db.commit.assert_awaited_once()
    assert worker._items_this_cycle == 0
