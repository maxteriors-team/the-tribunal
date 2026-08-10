"""Integration tests for the dispatch roster following workspace membership.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: a technician provisioned through the real bulk-member path lands on
the dispatch roster, the "one login, one roster row per workspace" index holds,
and a removed member stops being assignable without losing job history.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.field_service import Technician
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.bulk_members import BulkMemberItem
from app.services.field_service import (
    TechnicianService,
    ensure_member_on_roster,
    retire_member_from_roster,
)
from app.services.workspaces import bulk_create_members

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Crew Co", slug=f"crew-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


def _email() -> str:
    return f"roster-{uuid.uuid4().hex[:10]}@example.com"


async def _user(db, email: str, full_name: str | None = "Sam Rivera") -> User:
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x" * 20,
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def _roster(db, workspace_id: uuid.UUID) -> list[Technician]:
    return list(
        (
            await db.execute(
                select(Technician).where(Technician.workspace_id == workspace_id)
            )
        )
        .scalars()
        .all()
    )


async def test_bulk_provisioned_technician_is_taggable_to_jobs() -> None:
    """The whole point: hire a tech, and dispatch can assign them work."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        tech_email, office_email = _email(), _email()

        await bulk_create_members(
            db,
            workspace_id=ws.id,
            caller_role="owner",
            items=[
                BulkMemberItem(email=tech_email, full_name="Sam Rivera", role="technician"),
                BulkMemberItem(email=office_email, full_name="Dana Office", role="dispatcher"),
            ],
        )
        await db.flush()

        # The technician select reads active technicians for the workspace.
        listed = (await TechnicianService(db).list(ws.id, is_active=True))["items"]
        names = [tech.name for tech in listed]
        assert names == ["Sam Rivera"]
        assert listed[0].email == tech_email.lower()
        # A dispatcher runs the board rather than working on it.
        assert "Dana Office" not in names


async def test_one_login_gets_one_roster_row_per_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        user = await _user(db, _email())

        first = await ensure_member_on_roster(
            db, workspace_id=ws.id, user=user, role="technician"
        )
        second = await ensure_member_on_roster(
            db, workspace_id=ws.id, user=user, role="lead_technician"
        )

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert len(await _roster(db, ws.id)) == 1


async def test_roster_row_added_before_the_login_is_claimed_not_duplicated() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        email = _email()
        # A dispatcher typed the crew in by hand (or Jobber sync imported them)
        # before the hire had an account.
        typed_in = await TechnicianService(db).create(
            ws.id, {"name": "Sam R.", "email": email.upper()}
        )
        user = await _user(db, email)

        entry = await ensure_member_on_roster(
            db, workspace_id=ws.id, user=user, role="technician"
        )

        assert entry is not None
        assert entry.id == typed_in.id
        assert entry.user_id == user.id
        assert len(await _roster(db, ws.id)) == 1


async def test_removed_member_stops_being_assignable() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        user = await _user(db, _email())
        entry = await ensure_member_on_roster(
            db, workspace_id=ws.id, user=user, role="technician"
        )
        assert entry is not None

        assert await retire_member_from_roster(db, workspace_id=ws.id, user_id=user.id) == 1

        assert (await TechnicianService(db).list(ws.id, is_active=True))["items"] == []
        # The row itself survives, so any job they already worked keeps its
        # assignment history.
        rows = await _roster(db, ws.id)
        assert [(row.id, row.user_id, row.is_active) for row in rows] == [
            (entry.id, None, False)
        ]
