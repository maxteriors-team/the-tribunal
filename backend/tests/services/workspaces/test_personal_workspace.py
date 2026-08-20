"""Tests for personal-workspace provisioning (finding RF-001).

Every new/first-login user must resolve to a usable default workspace with an
owner membership and a default pipeline, otherwise the dashboard freezes on its
loading skeleton. ``ensure_personal_workspace`` must be idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.pipeline import Pipeline
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.pricing import PricingSettings
from app.schemas.proposal_wizard import ProposalWizardPayload, WizardFixtureQty
from app.services.quotes.quote_service import QuoteService
from app.services.workspaces import ensure_personal_workspace
from app.services.workspaces.default_sales_setup import STARTER_LANDSCAPE_SKUS

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_user(db, full_name: str | None) -> User:
    user = User(
        email=f"rf001-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("password123"),
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def test_ensure_personal_workspace_provisions_owner_membership_and_pipeline() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, "Jane Doe")

        workspace = await ensure_personal_workspace(db, user)
        await db.flush()

        assert workspace.name == "Jane's Workspace"
        assert workspace.is_active is True

        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.workspace_id == workspace.id,
                )
            )
        ).scalar_one()
        assert membership.role == "owner"
        assert membership.is_default is True

        pipelines = (
            (
                await db.execute(
                    select(Pipeline).where(Pipeline.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(pipelines) == 1

        pricing = PricingSettings.model_validate(workspace.settings["pricing"])
        referenced_skus = {
            item_id
            for tier in pricing.tiers
            for section in tier.sections
            for item_id in section.item_ids
        }
        catalog_items = (
            (await db.execute(select(CatalogItem).where(CatalogItem.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert referenced_skus == STARTER_LANDSCAPE_SKUS
        assert {item.sku for item in catalog_items} == referenced_skus
        assert all(item.is_active and item.unit_price > 0 for item in catalog_items)

        proposal = await QuoteService(db).preview_from_wizard(
            workspace.id,
            ProposalWizardPayload(
                categories=["landscape"],
                selected_tier="best",
                quantities=[
                    WizardFixtureQty(item_id="starter-estate-uplight", quantity=2)
                ],
            ),
        )
        estate_tier = next(tier for tier in proposal.tiers if tier.key == "best")
        uplight = next(
            line
            for line in estate_tier.lines
            if line.item_id == "starter-estate-uplight"
        )
        assert uplight.quantity == 2
        assert uplight.unit_price == 882
        assert uplight.line_total == 1764
        assert estate_tier.pricing.financed_total == 1764


async def test_ensure_personal_workspace_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, None)

        first = await ensure_personal_workspace(db, user)
        await db.flush()
        # No full_name falls back to the generic personal-workspace name.
        assert first.name == "My Workspace"

        again = await ensure_personal_workspace(db, user)
        await db.flush()
        assert again.id == first.id

        memberships = (
            (
                await db.execute(
                    select(WorkspaceMembership).where(
                        WorkspaceMembership.user_id == user.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships) == 1


async def test_ensure_personal_workspace_returns_existing_default() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, "Existing Owner")
        ws = Workspace(id=uuid.uuid4(), name="Existing", slug=f"existing-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        db.add(
            WorkspaceMembership(
                user_id=user.id, workspace_id=ws.id, role="owner", is_default=True
            )
        )
        await db.flush()

        resolved = await ensure_personal_workspace(db, user)
        assert resolved.id == ws.id
