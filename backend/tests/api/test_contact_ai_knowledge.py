"""Authorization and workspace-scope tests for contact AI knowledge routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership
from app.api.v1 import contacts as contacts_routes
from app.schemas.contact import ContactAIKnowledgeResponse

WORKSPACE_ID = uuid.uuid4()
CONTACT_ID = 42
FACT_ID = uuid.uuid4()


def _knowledge() -> ContactAIKnowledgeResponse:
    return ContactAIKnowledgeResponse(
        contact_id=CONTACT_ID,
        generated_at=datetime(2026, 8, 17, 12, tzinfo=UTC),
        structured_facts=[],
        next_action=None,
        memory_summary=None,
        memory_facts=[],
        conflicts=[],
    )


@asynccontextmanager
async def _client_as(
    role: str,
    *,
    knowledge: ContactAIKnowledgeResponse | None = None,
    fact_updated: bool = True,
) -> AsyncIterator[tuple[AsyncClient, MagicMock, MagicMock, MagicMock]]:
    app = FastAPI()
    app.include_router(
        contacts_routes.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )

    db = MagicMock()
    db.commit = AsyncMock()
    knowledge_service = MagicMock()
    knowledge_service.get_knowledge = AsyncMock(return_value=knowledge or _knowledge())
    memory_service = MagicMock()
    memory_service.update_summary = AsyncMock(return_value=True)
    memory_service.update_fact = AsyncMock(return_value=fact_updated)

    async def _user_override() -> SimpleNamespace:
        return SimpleNamespace(id=7, is_active=True)

    async def _membership_override() -> SimpleNamespace:
        return SimpleNamespace(role=role, workspace_id=WORKSPACE_ID, user_id=7)

    async def _db_override() -> AsyncIterator[MagicMock]:
        yield db

    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_membership] = _membership_override
    app.dependency_overrides[get_db] = _db_override

    with (
        patch.object(
            contacts_routes,
            "ContactAIKnowledgeService",
            return_value=knowledge_service,
        ),
        patch.object(
            contacts_routes,
            "ContactAIMemoryService",
            return_value=memory_service,
        ),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client, knowledge_service, memory_service, db


def _url(path: str = "") -> str:
    return f"/api/v1/workspaces/{WORKSPACE_ID}/contacts/{CONTACT_ID}/ai-knowledge{path}"


@pytest.mark.asyncio
async def test_crm_reader_can_read_private_no_store_projection() -> None:
    async with _client_as("member") as (client, knowledge_service, _, _db):
        response = await client.get(_url())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    knowledge_service.get_knowledge.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        contact_id=CONTACT_ID,
    )


@pytest.mark.asyncio
async def test_field_technician_cannot_read_contact_ai_knowledge() -> None:
    async with _client_as("technician") as (client, knowledge_service, _, _db):
        response = await client.get(_url())

    assert response.status_code == 403
    knowledge_service.get_knowledge.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "sales_rep", "technician"])
async def test_read_only_roles_cannot_correct_or_remove_generated_memory(role: str) -> None:
    async with _client_as(role) as (client, _, memory_service, _db):
        summary_response = await client.put(_url("/summary"), json={"value": "Corrected"})
        fact_response = await client.put(
            _url(f"/facts/{FACT_ID}"),
            json={"value": None},
        )

    assert summary_response.status_code == 403
    assert fact_response.status_code == 403
    memory_service.update_summary.assert_not_awaited()
    memory_service.update_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_crm_writer_corrects_summary_only_inside_path_workspace_and_contact() -> None:
    async with _client_as("manager") as (client, _, memory_service, db):
        response = await client.put(_url("/summary"), json={"value": "  Corrected summary  "})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    memory_service.update_summary.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        contact_id=CONTACT_ID,
        value="Corrected summary",
        operator_id=7,
    )
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_generated_or_out_of_scope_fact_is_not_exposed_as_editable() -> None:
    async with _client_as("manager", fact_updated=False) as (client, _, memory_service, db):
        response = await client.put(
            _url(f"/facts/{FACT_ID}"),
            json={"value": "Corrected fact"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Generated memory fact not found"
    memory_service.update_fact.assert_awaited_once_with(
        workspace_id=WORKSPACE_ID,
        contact_id=CONTACT_ID,
        fact_id=FACT_ID,
        value="Corrected fact",
        operator_id=7,
    )
    db.commit.assert_not_awaited()
