from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.workspace import Workspace
from app.services.quo.backfill import (
    QuoBackfillCounts,
    QuoHistoricalBackfill,
    QuoTenantMismatchError,
)
from app.services.quo.client import QuoClient

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "quo" / "historical_pages.json"
SINCE = datetime(2026, 8, 1, tzinfo=UTC)
UNTIL = datetime(2026, 8, 8, tzinfo=UTC)
pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.integration]


@asynccontextmanager
async def _db_session() -> AsyncIterator[AsyncSession]:
    test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await test_engine.dispose()


def _fixture_client(*, tenant_mismatch: bool = False) -> tuple[QuoClient, httpx.AsyncClient]:
    fixture: dict[str, Any] = json.loads(FIXTURE_PATH.read_text())
    fixture["phone_numbers"]["data"].extend(
        [
            {"id": "PNother-one", "number": "+14155550101"},
            {"id": "PNother-two", "number": "+14155550102"},
        ]
    )
    if tenant_mismatch:
        fixture["conversations"][0]["data"][0]["phoneNumberId"] = "PNforeign"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        token = request.url.params.get("pageToken")
        if path == "/v1/phone-numbers":
            return httpx.Response(200, json=fixture["phone_numbers"])
        if path == "/v1/users/USfixture":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "USfixture",
                        "firstName": "Morgan",
                        "lastName": "Operator",
                        "email": "morgan@example.com",
                    }
                },
            )
        if path.startswith("/contacts/"):
            contact = fixture["contacts"][0]["data"][0]
            fields = contact["defaultFields"]
            return httpx.Response(
                200,
                json={"data": {"id": contact["id"], **fields}},
            )
        if path == "/v1/conversations":
            assert request.url.params.get_list("phoneNumbers") == ["PNfixture"]
        pages = fixture[path.removeprefix("/v1/")]
        return httpx.Response(200, json=pages[1 if token else 0])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return QuoClient("fixture-key", client=http_client), http_client


async def _run(
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    client: QuoClient,
    *,
    apply: bool,
) -> QuoBackfillCounts:
    return await QuoHistoricalBackfill(
        db_session,
        workspace_id=workspace_id,
        organization_id="ORfixture",
        phone_number_id="PNfixture",
        phone_number="+14155552671",
        client=client,
        since=SINCE,
        until=UNTIL,
        apply=apply,
    ).run()


async def test_fixture_backfill_is_dry_idempotent_and_preserves_newer_fields() -> None:  # noqa: PLR0915
    client, http_client = _fixture_client()
    async with _db_session() as db:
        workspace = Workspace(
            name="Quo backfill fixture",
            slug=f"quo-backfill-{uuid.uuid4().hex}",
        )
        db.add(workspace)
        await db.commit()
        workspace_id = workspace.id

        try:
            dry_run = await _run(db, workspace_id, client, apply=False)
            assert dry_run.contacts.synced == 0
            assert dry_run.texts.synced == 2
            assert dry_run.calls.synced == 1
            assert (
                await db.scalar(select(Contact).where(Contact.workspace_id == workspace_id)) is None
            )

            await _run(db, workspace_id, client, apply=True)
            await _run(db, workspace_id, client, apply=True)

            contacts = list(
                await db.scalars(select(Contact).where(Contact.workspace_id == workspace_id))
            )
            messages = list(
                await db.scalars(
                    select(Message)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace_id)
                )
            )
            assert len(contacts) == 1
            assert len(messages) == 3
            assert {message.provider_message_id for message in messages} == {
                "ACmessage-in",
                "ACmessage-out",
                "ACcall",
            }

            contact = contacts[0]
            outbound = next(
                message for message in messages if message.provider_message_id == "ACmessage-out"
            )
            call = next(message for message in messages if message.provider_message_id == "ACcall")
            assert contact.email is None
            assert contact.phone_number == "+14155552672"
            assert outbound.body == "Fixture outbound text"
            assert outbound.provider_sender_user_id == "USfixture"
            assert outbound.sender_display_name == "Morgan Operator"
            contact.first_name = "Operator edit"
            outbound.status = MessageStatus.DELIVERED
            outbound.body = "Newer webhook body"
            outbound.delivered_at = datetime(2026, 8, 4, 10, 5, tzinfo=UTC)
            outbound.external_url = "https://example.invalid/newer"
            call.body = "Operator call note"
            call.transcript = "Newer webhook transcript"
            call.duration_seconds = 99
            await db.commit()

            await _run(db, workspace_id, client, apply=True)
            await db.refresh(contact)
            await db.refresh(outbound)
            await db.refresh(call)

            assert contact.first_name == "Operator edit"
            assert outbound.status == MessageStatus.DELIVERED
            assert outbound.body == "Newer webhook body"
            assert outbound.delivered_at == datetime(2026, 8, 4, 10, 5, tzinfo=UTC)
            assert outbound.external_url == "https://example.invalid/newer"
            assert call.body == "Operator call note"
            assert call.transcript == "Newer webhook transcript"
            assert call.duration_seconds == 99
        finally:
            persisted_workspace = await db.get(Workspace, workspace_id)
            if persisted_workspace is not None:
                await db.delete(persisted_workspace)
                await db.commit()
            await http_client.aclose()


async def test_fixture_backfill_stops_on_phone_number_tenant_mismatch() -> None:
    client, http_client = _fixture_client(tenant_mismatch=True)
    async with _db_session() as db:
        workspace = Workspace(
            name="Quo backfill tenant mismatch",
            slug=f"quo-backfill-mismatch-{uuid.uuid4().hex}",
        )
        db.add(workspace)
        await db.commit()
        workspace_id = workspace.id

        try:
            with pytest.raises(QuoTenantMismatchError):
                await _run(db, workspace_id, client, apply=True)
            assert (
                await db.scalar(select(Contact).where(Contact.workspace_id == workspace_id)) is None
            )
        finally:
            persisted_workspace = await db.get(Workspace, workspace_id)
            if persisted_workspace is not None:
                await db.delete(persisted_workspace)
                await db.commit()
            await http_client.aclose()
