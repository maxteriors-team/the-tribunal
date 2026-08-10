"""Regression test for POST /appointments response serialization.

``AppointmentResponse`` embeds a nested contact summary. ``create_appointment``
used to return the freshly committed ORM instance with ``contact`` unloaded, so
FastAPI's response validation triggered an async lazy-load after the request
session had committed. That raises ``MissingGreenlet`` and turns a *successful*
booking into a 500: the row is written, but the operator sees an error and is
invited to retry — i.e. silent double-booking.

The failure only reproduces against a real async session (a mocked ``db`` has no
lazy-load semantics), so this test drives the router with a live DB session and
asserts on the serialized HTTP response, not on the service return value.

Requires a local Postgres (``make dev.db`` + ``make migrate``):

    uv run pytest -m integration tests/integration/test_appointment_create_response.py
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import appointments as appointments_module
from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.workspace import Workspace

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan: no background workers, no Redis."""
    yield


@asynccontextmanager
async def _seeded_workspace() -> AsyncIterator[tuple[uuid.UUID, int]]:
    """Seed a workspace + contact, yield their ids, then delete the workspace.

    The engine pool is disposed around the body because pytest-asyncio gives
    each test a fresh event loop, and a pooled asyncpg connection bound to a
    closed loop surfaces later as ``Event loop is closed``.
    """
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Appointment Serialization Co",
            slug=f"appt-serialize-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()

        phone_number = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Booked",
            last_name="Customer",
            phone_number=phone_number,
            phone_hash=hash_phone(phone_number),
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)
        workspace_id, contact_id = workspace.id, contact.id

    try:
        yield workspace_id, contact_id
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()
        await engine.dispose()


def _make_app(workspace_id: uuid.UUID) -> FastAPI:
    """Mount the appointments router with a real DB session and stub auth."""
    app = FastAPI(lifespan=_test_lifespan)

    ws = MagicMock()
    ws.id = workspace_id
    ws.is_active = True

    user = MagicMock()
    user.id = 1
    user.is_active = True

    async def override_get_db() -> AsyncIterator[Any]:
        async with AsyncSessionLocal() as session:
            yield session

    async def override_get_workspace() -> MagicMock:
        return ws

    async def override_get_current_user() -> MagicMock:
        return user

    async def override_get_membership() -> MagicMock:
        membership = MagicMock()
        membership.role = "owner"
        membership.workspace_id = workspace_id
        membership.user_id = user.id
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        appointments_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/appointments",
    )
    return app


async def test_create_appointment_serializes_nested_contact() -> None:
    """A created appointment returns 201 with the nested contact populated."""
    async with _seeded_workspace() as (workspace_id, contact_id):
        app = _make_app(workspace_id)
        scheduled_at = datetime.now(UTC) + timedelta(days=1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{workspace_id}/appointments",
                json={
                    "contact_id": contact_id,
                    "scheduled_at": scheduled_at.isoformat(),
                    "duration_minutes": 60,
                    "service_type": "Roof Wash",
                },
            )

        # A lazy-load of ``contact`` during response validation surfaces here as
        # a 500, not as a test error, so assert on the status explicitly.
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["contact_id"] == contact_id
        assert body["service_type"] == "Roof Wash"
        assert body["status"] == "scheduled"
        # The nested summary is the part that used to blow up.
        assert body["contact"] is not None
        assert body["contact"]["first_name"] == "Booked"
