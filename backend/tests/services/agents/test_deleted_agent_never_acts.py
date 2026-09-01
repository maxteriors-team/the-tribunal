"""A deleted agent must never be picked to talk to a customer.

Soft delete keeps the row so history still resolves, which means every code
path that *chooses* an agent to act with has to exclude deleted ones itself.
Three paths pick an agent and then send outbound messages under the operator's
name, and each one used to happily pick a deleted agent:

- campaign SMS fallback, pinned by ``Campaign.sms_fallback_agent_id`` (the FK
  only clears on a hard delete, so the pointer outlives the agent)
- reactivation drip bootstrap, matched by agent *name*
- onboarding's ``get_reactivation_agent``, matched by name then by "earliest
  text agent"

This is the same failure as the auto-seeding bug: the operator deletes an
agent, and it keeps talking to their customers anyway.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.services.onboarding.exceptions import OnboardingValidationError
from app.services.onboarding.workspace_setup import (
    REACTIVATION_AGENT_NAME,
    get_reactivation_agent,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Del", slug=f"del-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


def _deleted(**kwargs) -> Agent:
    return Agent(deleted_at=datetime.now(UTC), is_active=False, **kwargs)


async def test_onboarding_does_not_return_a_deleted_reactivation_agent() -> None:
    # Pooled connections belong to the previous test's event loop; drop them
    # first (same pattern as tests/integration/test_attendance.py).
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        db.add(
            _deleted(
                workspace_id=ws.id,
                name=REACTIVATION_AGENT_NAME,
                system_prompt="x",
                channel_mode="text",
            )
        )
        await db.flush()

        # The name matches, but the agent is deleted -- and there is no other
        # text agent to fall back to, so this must raise rather than hand back
        # a deleted agent for texting past customers.
        with pytest.raises(OnboardingValidationError):
            await get_reactivation_agent(db=db, workspace_id=ws.id)


async def test_onboarding_falls_back_past_a_deleted_agent_to_a_live_one() -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        # Deleted, and created first -- so an unfiltered "earliest text agent"
        # fallback would pick exactly this one.
        db.add(
            _deleted(
                workspace_id=ws.id,
                name="Deleted Text Agent",
                system_prompt="x",
                channel_mode="text",
            )
        )
        await db.flush()
        live = Agent(
            workspace_id=ws.id,
            name="Live Text Agent",
            system_prompt="x",
            channel_mode="text",
            is_active=True,
        )
        db.add(live)
        await db.flush()

        resolved = await get_reactivation_agent(db=db, workspace_id=ws.id)

        assert resolved.id == live.id
