"""Fixtures for opportunities service tests.

The DB-backed (``integration``) tests in this package use the global
``AsyncSessionLocal`` engine. Because pytest-asyncio gives each test a fresh,
function-scoped event loop, the engine's asyncpg pool can otherwise hold
connections bound to an already-closed loop, surfacing as ``Event loop is
closed`` / "attached to a different loop" when integration tests run
back-to-back. Disposing the pool around each test guarantees fresh connections
bind to the current loop.
"""

from __future__ import annotations

import pytest

from app.db.session import engine


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (cheap; no I/O if idle)."""
    await engine.dispose()
    yield
    await engine.dispose()
