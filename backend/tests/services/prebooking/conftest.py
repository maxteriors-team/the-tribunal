"""Fixtures for pre-booking service tests.

The DB-backed (``integration``) tests here use the global ``AsyncSessionLocal``
engine. pytest-asyncio gives each test a fresh, function-scoped event loop, so
the engine's asyncpg pool can otherwise hold connections bound to an
already-closed loop. Disposing the pool around each test guarantees fresh
connections bind to the current loop — same rationale as
``tests/services/opportunities/conftest.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.db.session import engine


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()
