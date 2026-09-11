"""Exact contact lookup through real auth, workspace dependencies and PostgreSQL.

All rows live inside an outer transaction that is rolled back, even when a
service commits. No workers start and no message-sending endpoint is called.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.api.v1.conversations import router
from app.core.config import settings
from app.core.security import create_access_token
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

pytestmark = pytest.mark.integration


@dataclass
class Scenario:
    app: FastAPI
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    user_id: int
    contact_id: int
    missing_contact_id: int
    imported_contact_id: int
    other_contact_id: int
    conversation_id: uuid.UUID
    imported_conversation_id: uuid.UUID
    other_conversation_id: uuid.UUID
    agent_id: uuid.UUID
    other_agent_id: uuid.UUID

    @property
    def url(self) -> str:
        return f"/api/v1/workspaces/{self.workspace_id}/conversations"


@asynccontextmanager
async def contact_lookup_scenario() -> AsyncIterator[Scenario]:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            try:
                async with sessions() as db:
                    suffix = uuid.uuid4().hex
                    workspace = Workspace(name="F07 fixture", slug=f"f07-{suffix}")
                    other_workspace = Workspace(name="F07 other", slug=f"f07-other-{suffix}")
                    user = User(email=f"f07-{suffix}@example.com", hashed_password="not-used")
                    db.add_all([workspace, other_workspace, user])
                    await db.flush()
                    db.add(
                        WorkspaceMembership(
                            workspace_id=workspace.id, user_id=user.id, role="owner"
                        )
                    )
                    contacts = [
                        Contact(
                            workspace_id=workspace.id,
                            first_name="Same",
                            last_name="Name",
                            phone_number=f"+1202555010{i}",
                        )
                        for i in range(4)
                    ]
                    contact, missing, imported_contact, newer_contact = contacts
                    other_contact = Contact(
                        workspace_id=other_workspace.id,
                        first_name="Same",
                        last_name="Name",
                        phone_number="+12025550100",
                    )
                    agent = Agent(workspace_id=workspace.id, name="F07 agent", system_prompt="Test")
                    other_agent = Agent(
                        workspace_id=other_workspace.id,
                        name="F07 other agent",
                        system_prompt="Test",
                    )
                    db.add_all([*contacts, other_contact, agent, other_agent])
                    await db.flush()
                    now = datetime.now(UTC)
                    conversation = Conversation(
                        workspace_id=workspace.id,
                        contact_id=contact.id,
                        last_message_at=now - timedelta(days=200),
                        unread_count=3,
                        assigned_agent_id=agent.id,
                        ai_enabled=True,
                        ai_paused=True,
                    )
                    imported = Conversation(
                        workspace_id=workspace.id,
                        contact_id=imported_contact.id,
                        last_message_at=now - timedelta(days=200),
                        source_provider="quo",
                        unread_count=2,
                        ai_enabled=False,
                    )
                    other = Conversation(
                        workspace_id=other_workspace.id,
                        contact_id=other_contact.id,
                        last_message_at=now,
                    )
                    db.add_all(
                        [
                            conversation,
                            imported,
                            other,
                            Conversation(
                                workspace_id=workspace.id,
                                contact_id=contact.id,
                                last_message_at=now - timedelta(days=201),
                            ),
                            Conversation(workspace_id=workspace.id, contact_id=contact.id),
                            *[
                                Conversation(
                                    workspace_id=workspace.id,
                                    contact_id=newer_contact.id,
                                    last_message_at=now - timedelta(minutes=i),
                                )
                                for i in range(101)
                            ],
                        ]
                    )
                    await db.commit()

                async def local_db() -> AsyncIterator[AsyncSession]:
                    async with sessions() as session:
                        yield session

                app = FastAPI()
                app.include_router(router, prefix="/api/v1/workspaces/{workspace_id}/conversations")
                # Only the connection is substituted; auth and tenancy run unchanged.
                app.dependency_overrides[get_db] = local_db
                yield Scenario(
                    app=app,
                    workspace_id=workspace.id,
                    other_workspace_id=other_workspace.id,
                    user_id=user.id,
                    contact_id=contact.id,
                    missing_contact_id=missing.id,
                    imported_contact_id=imported_contact.id,
                    other_contact_id=other_contact.id,
                    conversation_id=conversation.id,
                    imported_conversation_id=imported.id,
                    other_conversation_id=other.id,
                    agent_id=agent.id,
                    other_agent_id=other_agent.id,
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    async with contact_lookup_scenario() as value:
        yield value


@pytest.fixture
async def client(scenario: Scenario) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=scenario.app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {create_access_token({'sub': str(scenario.user_id)})}"},
    ) as value:
        yield value


async def test_finds_old_contact_before_pagination_without_clearing_unread(
    scenario: Scenario, client: AsyncClient
) -> None:
    first_page = await client.get(scenario.url, params={"page_size": 100})
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 100
    assert all(row["contact_id"] != scenario.contact_id for row in first_page.json()["items"])

    for _ in range(2):
        response = await client.get(
            scenario.url, params={"contact_id": scenario.contact_id, "page_size": 1}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["pages"] == 3
        assert len(body["items"]) == 1
        row = body["items"][0]
        assert row["id"] == str(scenario.conversation_id)
        assert row["contact_id"] == scenario.contact_id
        assert row["workspace_id"] == str(scenario.workspace_id)
        assert row["unread_count"] == 3
        assert row["assigned_agent_id"] == str(scenario.agent_id)
        assert row["ai_enabled"] is True
        assert row["ai_paused"] is True

    read = await client.post(f"{scenario.url}/{scenario.conversation_id}/read")
    assert read.status_code == 200
    assert read.json()["unread_count"] == 0
    unread = await client.get(
        scenario.url, params={"contact_id": scenario.contact_id, "unread_only": True}
    )
    assert unread.status_code == 200
    assert unread.json()["items"] == []


async def test_missing_or_foreign_contact_never_falls_back_to_name_or_workspace_scan(
    scenario: Scenario, client: AsyncClient
) -> None:
    for contact_id in (scenario.missing_contact_id, scenario.other_contact_id, 9223372036854775807):
        response = await client.get(scenario.url, params={"contact_id": contact_id})
        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["total"] == 0

    denied = await client.get(
        f"/api/v1/workspaces/{scenario.other_workspace_id}/conversations",
        params={"contact_id": scenario.other_contact_id},
    )
    assert denied.status_code == 404
    unauthenticated = await client.get(scenario.url, headers={"Authorization": ""})
    assert unauthenticated.status_code == 401


@pytest.mark.parametrize("contact_id", ["0", "-1", "1.5", "not-an-id", "9223372036854775808"])
async def test_contact_filter_is_a_validated_database_id(
    scenario: Scenario, client: AsyncClient, contact_id: str
) -> None:
    response = await client.get(scenario.url, params={"contact_id": contact_id})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "contact_id"]


async def test_old_conversation_ai_controls_stay_scoped(
    scenario: Scenario, client: AsyncClient
) -> None:
    url = f"{scenario.url}/{scenario.conversation_id}"
    toggled = await client.post(f"{url}/ai/toggle", json={"enabled": False})
    assert toggled.status_code == 200
    assert toggled.json() == {"ai_enabled": False}
    unassigned = await client.post(f"{url}/assign", json={"agent_id": None})
    assert unassigned.status_code == 200
    reassigned = await client.post(f"{url}/assign", json={"agent_id": str(scenario.agent_id)})
    assert reassigned.status_code == 200
    foreign_agent = await client.post(
        f"{url}/assign", json={"agent_id": str(scenario.other_agent_id)}
    )
    assert foreign_agent.status_code == 404
    foreign_thread = await client.post(
        f"{scenario.url}/{scenario.other_conversation_id}/ai/toggle", json={"enabled": False}
    )
    assert foreign_thread.status_code == 404
    response = await client.get(
        scenario.url, params={"contact_id": scenario.contact_id, "page_size": 1}
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["ai_enabled"] is False
    assert response.json()["items"][0]["assigned_agent_id"] == str(scenario.agent_id)


async def test_old_imported_conversation_is_returned_but_remains_read_only(
    scenario: Scenario, client: AsyncClient
) -> None:
    response = await client.get(scenario.url, params={"contact_id": scenario.imported_contact_id})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    row = response.json()["items"][0]
    assert row["id"] == str(scenario.imported_conversation_id)
    assert row["source_provider"] == "quo"
    assert row["unread_count"] == 2
    url = f"{scenario.url}/{scenario.imported_conversation_id}"
    toggled = await client.post(f"{url}/ai/toggle", json={"enabled": True})
    assigned = await client.post(f"{url}/assign", json={"agent_id": str(scenario.agent_id)})
    for response in (toggled, assigned):
        assert response.status_code == 409
        assert response.json()["detail"] == "Imported conversations are read-only"
