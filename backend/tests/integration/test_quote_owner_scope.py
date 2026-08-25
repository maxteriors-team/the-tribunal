"""Database-backed sales quote ownership boundaries."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.quotes import _scoped_quote
from app.db.session import AsyncSessionLocal
from app.models.quote import Quote
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_sales_reps_cannot_cross_quote_owners_but_manager_can() -> None:
    suffix = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Quote owner scope", slug=f"quote-owner-{suffix}")
        sales_a = User(
            email=f"quote-a-{suffix}@example.com",
            full_name="Quote Sales A",
            hashed_password="not-used",
        )
        sales_b = User(
            email=f"quote-b-{suffix}@example.com",
            full_name="Quote Sales B",
            hashed_password="not-used",
        )
        manager = User(
            email=f"quote-manager-{suffix}@example.com",
            full_name="Quote Manager",
            hashed_password="not-used",
        )
        db.add_all([workspace, sales_a, sales_b, manager])
        await db.flush()
        membership_a = WorkspaceMembership(
            workspace_id=workspace.id, user_id=sales_a.id, role="sales_rep"
        )
        membership_b = WorkspaceMembership(
            workspace_id=workspace.id, user_id=sales_b.id, role="sales_rep"
        )
        manager_membership = WorkspaceMembership(
            workspace_id=workspace.id, user_id=manager.id, role="manager"
        )
        quote_a = Quote(
            workspace_id=workspace.id,
            number=f"QA-{suffix[:8]}",
            assigned_user_id=sales_a.id,
            created_by_id=sales_a.id,
        )
        quote_b = Quote(
            workspace_id=workspace.id,
            number=f"QB-{suffix[:8]}",
            assigned_user_id=sales_b.id,
            created_by_id=sales_b.id,
        )
        legacy_quote_a = Quote(
            workspace_id=workspace.id,
            number=f"QL-{suffix[:8]}",
            assigned_user_id=None,
            created_by_id=sales_a.id,
        )
        db.add_all(
            [membership_a, membership_b, manager_membership, quote_a, quote_b, legacy_quote_a]
        )
        await db.commit()

        try:
            assert (
                await _scoped_quote(workspace.id, quote_a.id, sales_a, membership_a, db) is quote_a
            )
            assert (
                await _scoped_quote(workspace.id, legacy_quote_a.id, sales_a, membership_a, db)
                is legacy_quote_a
            )
            with pytest.raises(HTTPException) as exc_info:
                await _scoped_quote(workspace.id, quote_b.id, sales_a, membership_a, db)
            assert exc_info.value.status_code == 404
            assert (
                await _scoped_quote(workspace.id, quote_b.id, manager, manager_membership, db)
                is quote_b
            )
        finally:
            await db.delete(workspace)
            await db.delete(sales_a)
            await db.delete(sales_b)
            await db.delete(manager)
            await db.commit()
