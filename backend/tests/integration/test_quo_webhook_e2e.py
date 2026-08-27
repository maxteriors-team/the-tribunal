"""Signed Quo webhook fixtures through the HTTP boundary and real database."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from svix.webhooks import Webhook

from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel, MessageStatus
from app.models.webhook_signature import SeenWebhookSignature
from app.models.workspace import Workspace, WorkspaceIntegration
from app.services.compliance.outbound_compliance import (
    DirectOutboundComplianceRequest,
    OutboundComplianceService,
)
from app.services.webhook_replay import (
    SignatureClaimOutcome,
    claim_webhook_signature_in_transaction,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.integration]

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "quo" / "signed_activity_sequence.json"
)


def _fixture(run_id: str) -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text().replace("__RUN_ID__", run_id))


def _signed_headers(signing_key: str, delivery_id: str, body: bytes) -> dict[str, str]:
    signed_at = datetime.now(UTC)
    timestamp = int(signed_at.timestamp())
    signature = Webhook(signing_key).sign(delivery_id, signed_at, body.decode())
    return {
        "content-type": "application/json",
        "webhook-id": delivery_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": signature,
    }


async def _post_event(
    client: AsyncClient,
    *,
    integration_id: uuid.UUID,
    signing_key: str,
    delivery_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post(
        f"/webhooks/quo/{integration_id}",
        content=body,
        headers=_signed_headers(signing_key, delivery_id, body),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_failed_dispatch_rollback_allows_same_delivery_retry() -> None:
    delivery_id = f"quo_retry_{uuid.uuid4().hex}"
    log = MagicMock()
    async with AsyncSessionLocal() as db:
        first = await claim_webhook_signature_in_transaction(
            db,
            "quo",
            delivery_id,
            log=log,
        )
        assert first.outcome is SignatureClaimOutcome.CLAIMED
        await db.rollback()

    async with AsyncSessionLocal() as db:
        retry = await claim_webhook_signature_in_transaction(
            db,
            "quo",
            delivery_id,
            log=log,
        )
        assert retry.outcome is SignatureClaimOutcome.CLAIMED
        await db.commit()

    async with AsyncSessionLocal() as db:
        replay = await claim_webhook_signature_in_transaction(
            db,
            "quo",
            delivery_id,
            log=log,
        )
        assert replay.outcome is SignatureClaimOutcome.REPLAY
        await db.rollback()
        await db.execute(
            delete(SeenWebhookSignature).where(
                SeenWebhookSignature.provider == "quo",
                SeenWebhookSignature.signature == delivery_id,
            )
        )
        await db.commit()


async def test_signed_activity_sequence_is_tenant_safe_idempotent_and_sms_compliant() -> None:  # noqa: PLR0915
    run_id = uuid.uuid4().hex[:16]
    fixture = _fixture(run_id)
    events: dict[str, dict[str, Any]] = fixture["events"]
    organization_id = f"OR_{run_id}"
    signing_key = "whsec_" + base64.b64encode(run_id.encode().ljust(32, b"q")).decode()
    delivery_ids: list[str] = []
    # Integration modules use separate pytest event loops; discard pooled connections
    # created by an earlier module before this test opens its first session.
    await engine.dispose(close=False)

    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Quo signed webhook E2E", slug=f"quo-e2e-{run_id}")
        other_workspace = Workspace(name="Quo tenant isolation E2E", slug=f"quo-other-{run_id}")
        db.add_all([workspace, other_workspace])
        await db.flush()
        integration = WorkspaceIntegration(
            workspace_id=workspace.id,
            integration_type="quo",
            credentials={
                "api_key": f"quo_fixture_{run_id}",
                "organization_id": organization_id,
                "webhook_id": f"WH_{run_id}",
                "webhook_signing_key": signing_key,
                "webhook_api_version": "2026-03-30",
                "phone_number_id": f"PN_{run_id}",
                "phone_number": fixture["workspace_phone"],
            },
            is_active=True,
        )
        other_contact = Contact(
            workspace_id=other_workspace.id,
            first_name="Other tenant",
            phone_number=fixture["contact_phone"],
        )
        db.add_all([integration, other_contact])
        await db.commit()
        workspace_id = workspace.id
        other_workspace_id = other_workspace.id
        integration_id = integration.id

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            for name in ("inbound", "outbound_failed", "outbound_delivered"):
                delivery_id = f"msg_{name}_{run_id}"
                delivery_ids.append(delivery_id)
                assert await _post_event(
                    client,
                    integration_id=integration_id,
                    signing_key=signing_key,
                    delivery_id=delivery_id,
                    payload=events[name],
                ) == {"status": "ok"}

            duplicate_id = delivery_ids[-1]
            assert await _post_event(
                client,
                integration_id=integration_id,
                signing_key=signing_key,
                delivery_id=duplicate_id,
                payload=events["outbound_delivered"],
            ) == {"status": "ok", "deduped": "true", "reason": "already_processed"}

            stale_delivery_id = f"msg_stale_failed_{run_id}"
            delivery_ids.append(stale_delivery_id)
            assert await _post_event(
                client,
                integration_id=integration_id,
                signing_key=signing_key,
                delivery_id=stale_delivery_id,
                payload=events["outbound_failed"],
            ) == {"status": "ok"}

            for name in ("stop", "call_completed", "call_summary", "call_transcript"):
                delivery_id = f"msg_{name}_{run_id}"
                delivery_ids.append(delivery_id)
                assert await _post_event(
                    client,
                    integration_id=integration_id,
                    signing_key=signing_key,
                    delivery_id=delivery_id,
                    payload=events[name],
                ) == {"status": "ok"}

        async with AsyncSessionLocal() as db:
            contacts = list(
                (
                    await db.scalars(select(Contact).where(Contact.workspace_id == workspace_id))
                ).all()
            )
            assert len(contacts) == 1
            contact = contacts[0]
            assert contact.phone_number == fixture["contact_phone"]
            assert contact.sms_consent_status == "opted_out"
            sms_gate = await OutboundComplianceService().evaluate_direct(
                DirectOutboundComplianceRequest(
                    workspace_id=workspace_id,
                    channel="sms",
                    action_type="manual_sms",
                    now=datetime.now(UTC),
                    phone_number=fixture["contact_phone"],
                    sms_consent_status="opted_in",
                ),
                db,
            )
            assert not sms_gate.allowed
            assert sms_gate.reason == "global_opt_out"

            other_contacts = list(
                (
                    await db.scalars(
                        select(Contact).where(Contact.workspace_id == other_workspace_id)
                    )
                ).all()
            )
            assert len(other_contacts) == 1
            assert other_contacts[0].first_name == "Other tenant"
            assert other_contacts[0].sms_consent_status != "opted_out"
            assert not (
                await db.scalar(
                    select(Conversation.id).where(Conversation.workspace_id == other_workspace_id)
                )
            )

            messages = list(
                (
                    await db.scalars(
                        select(Message)
                        .join(Conversation)
                        .where(Conversation.workspace_id == workspace_id)
                        .order_by(Message.created_at, Message.id)
                    )
                ).all()
            )
            assert len(messages) == 4
            assert len({message.conversation_id for message in messages}) == 1

            outbound = next(
                message
                for message in messages
                if message.provider_message_id == f"AC_outbound_{run_id}"
            )
            assert outbound.status == MessageStatus.DELIVERED
            assert outbound.delivered_at is not None
            assert outbound.error_code is None

            voice = next(message for message in messages if message.channel == MessageChannel.VOICE)
            assert voice.provider_message_id == f"AC_call_{run_id}"
            assert voice.status == MessageStatus.COMPLETED
            assert voice.duration_seconds == 42
            assert voice.body == (
                "Customer requested a patio quote. Next steps: Send the estimate tomorrow."
            )
            assert voice.transcript is not None
            assert "Please send the patio quote tomorrow." in voice.transcript
            assert all(message.source_provider == "quo" for message in messages)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(SeenWebhookSignature).where(
                    SeenWebhookSignature.provider == "quo",
                    SeenWebhookSignature.signature.in_(delivery_ids),
                )
            )
            workspace = await db.get(Workspace, workspace_id)
            other_workspace = await db.get(Workspace, other_workspace_id)
            if workspace is not None:
                await db.delete(workspace)
            if other_workspace is not None:
                await db.delete(other_workspace)
            await db.commit()
        await engine.dispose()
