"""Database-backed Quo contact/message mirroring contracts."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageDirection, MessageStatus
from app.models.opt_out import GlobalOptOut
from app.models.workspace import Workspace
from app.services.quo.client import QuoClient
from app.services.quo.sync import QuoSyncError, QuoSyncService
from app.services.webhooks.quo import QuoWebhookEvent

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.integration]

ORGANIZATION_ID = "OR_quo_sync_test"
WORKSPACE_PHONE = "+12025550101"
CONTACT_PHONE = "+14155552671"


def _event(
    event_type: str,
    resource: dict[str, object],
    *,
    contact_ids: list[str] | None = None,
    event_at: datetime | None = None,
) -> QuoWebhookEvent:
    unique = uuid.uuid4().hex
    return QuoWebhookEvent(
        delivery_id=f"delivery_{unique}",
        event_id=f"event_{unique}",
        event_type=event_type,
        api_version="2026-03-30",
        organization_id=ORGANIZATION_ID,
        created_at=(event_at or datetime.now(UTC)).isoformat(),
        data={
            "context": {
                "orgId": ORGANIZATION_ID,
                "contactIds": contact_ids or [],
            },
            "resource": resource,
            "links": {"deepLink": "https://my.quo.com/inbox/test"},
        },
    )


def _message_resource(
    resource_id: str,
    *,
    direction: str,
    created_at: datetime,
    text: str = "Hello",
) -> dict[str, object]:
    incoming = direction == "incoming"
    return {
        "id": resource_id,
        "direction": direction,
        "status": "received" if incoming else "delivered",
        "senderIdentifier": CONTACT_PHONE if incoming else WORKSPACE_PHONE,
        "recipientIdentifiers": [WORKSPACE_PHONE if incoming else CONTACT_PHONE],
        "userId": "US_test" if not incoming else None,
        "phoneNumberId": "PN_test",
        "createdAt": created_at.isoformat(),
        "updatedAt": created_at.isoformat(),
        "text": text,
        "media": [],
    }


def _voice_event(
    event_type: str,
    resource: dict[str, object],
    *,
    contact_id: str = "CT_voice",
    event_at: datetime | None = None,
) -> QuoWebhookEvent:
    unique = uuid.uuid4().hex
    return QuoWebhookEvent(
        delivery_id=f"delivery_{unique}",
        event_id=f"event_{unique}",
        event_type=event_type,
        api_version="2026-03-30",
        organization_id=ORGANIZATION_ID,
        created_at=(event_at or datetime.now(UTC)).isoformat(),
        data={
            "context": {
                "orgId": ORGANIZATION_ID,
                "phoneNumberId": "PN_test",
                "contacts": {"ids": [contact_id], "external": []},
                "participants": [
                    {"phoneNumber": CONTACT_PHONE},
                    {"phoneNumber": WORKSPACE_PHONE},
                ],
            },
            "resource": resource,
            "links": {"quo": "https://my.quo.com/inbox/calls/test"},
        },
    )


def _call_resource(
    call_id: str,
    *,
    created_at: datetime,
    status: str = "answered",
    duration: int = 65,
    direction: str = "incoming",
) -> dict[str, object]:
    return {
        "id": call_id,
        "direction": direction,
        "participants": [
            {"phoneNumber": CONTACT_PHONE},
            {"phoneNumber": WORKSPACE_PHONE},
        ],
        "status": status,
        "createdAt": created_at.isoformat(),
        "updatedAt": (created_at + timedelta(seconds=duration)).isoformat(),
        "duration": duration,
        "recordingUrl": "https://recordings.example.test/must-not-be-used",
    }


def _service(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    fetched_contact: dict[str, object] | None = None,
) -> QuoSyncService:
    client = MagicMock(spec=QuoClient)
    client.get_contact = AsyncMock(return_value=fetched_contact)
    return QuoSyncService(
        db,
        workspace_id=workspace_id,
        organization_id=ORGANIZATION_ID,
        client=client,
    )


async def _workspace(db: AsyncSession, label: str) -> Workspace:
    suffix = uuid.uuid4().hex
    workspace = Workspace(name=label, slug=f"quo-{suffix}")
    db.add(workspace)
    await db.flush()
    return workspace


async def test_contact_update_creates_contact_and_preserves_it_on_delete() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo contact creation")
        resource: dict[str, object] = {
            "id": "CT_created",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "company": "Analytical Engines",
            "emails": ["ADA@example.com"],
            "phoneNumbers": [CONTACT_PHONE],
        }
        service = _service(db, workspace.id)

        await service.process(_event("contact.updated", resource), MagicMock())
        await service.process(_event("contact.deleted", resource), MagicMock())
        await db.commit()

        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.workspace_id == workspace.id,
                    Contact.external_source == "quo",
                    Contact.external_id == "CT_created",
                )
            )
        ).scalar_one()
        assert contact.first_name == "Ada"
        assert contact.last_name == "Lovelace"
        assert contact.email == "ada@example.com"
        assert contact.company_name == "Analytical Engines"

        await db.delete(workspace)
        await db.commit()


async def test_message_matches_quo_external_id_before_phone_hash() -> None:
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo external match")
        external_match = Contact(
            workspace_id=workspace.id,
            first_name="External match",
            phone_number="+14155552672",
            external_source="quo",
            external_id="CT_match",
        )
        phone_match = Contact(
            workspace_id=workspace.id,
            first_name="Phone match",
            phone_number=CONTACT_PHONE,
        )
        db.add_all([external_match, phone_match])
        await db.flush()

        resource = _message_resource(
            f"AC_external_{uuid.uuid4().hex}",
            direction="incoming",
            created_at=occurred_at,
        )
        resource["media"] = [{"type": "image/jpeg", "url": "https://media.example.test/a"}]
        await _service(db, workspace.id).process(
            _event("message.received", resource, contact_ids=["CT_match"]),
            MagicMock(),
        )
        await db.commit()

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        message = (
            await db.execute(select(Message).where(Message.conversation_id == conversation.id))
        ).scalar_one()
        assert conversation.contact_id == external_match.id
        assert conversation.contact_phone_hash == hash_phone(CONTACT_PHONE)
        assert conversation.workspace_phone_hash == hash_phone(WORKSPACE_PHONE)
        assert conversation.source_provider == "quo"
        assert conversation.ai_enabled is False
        assert conversation.unread_count == 1
        assert message.source_provider == "quo"
        assert message.external_url == "https://my.quo.com/inbox/test"
        assert message.direction == MessageDirection.INBOUND
        assert "[Quo attachment: image/jpeg]" in message.body
        assert external_match.last_engaged_at == occurred_at
        assert phone_match.last_engaged_at is None

        await db.delete(workspace)
        await db.commit()


async def test_contact_update_only_fills_blank_identity_fields() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo identity conflicts")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Operator First",
            last_name="",
            email="operator@example.com",
            company_name="Operator Company",
            phone_number=CONTACT_PHONE,
        )
        db.add(contact)
        await db.flush()

        await _service(db, workspace.id).process(
            _event(
                "contact.updated",
                {
                    "id": "CT_conflict",
                    "firstName": "Quo First",
                    "lastName": "Quo Last",
                    "emails": ["quo@example.com"],
                    "company": "Quo Company",
                    "phoneNumbers": [CONTACT_PHONE],
                },
            ),
            MagicMock(),
        )
        await db.commit()

        assert contact.first_name == "Operator First"
        assert contact.last_name == "Quo Last"
        assert contact.email == "operator@example.com"
        assert contact.company_name == "Operator Company"
        assert contact.external_source == "quo"
        assert contact.external_id == "CT_conflict"

        await db.delete(workspace)
        await db.commit()


async def test_duplicate_and_out_of_order_delivery_do_not_regress_message() -> None:
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo delivery ordering")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Delivery",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_delivery",
        )
        db.add(contact)
        await db.flush()
        resource_id = f"AC_delivery_{uuid.uuid4().hex}"
        resource = _message_resource(resource_id, direction="outgoing", created_at=occurred_at)
        service = _service(db, workspace.id)

        await service.process(
            _event(
                "message.delivered",
                resource,
                contact_ids=["CT_delivery"],
                event_at=occurred_at + timedelta(minutes=2),
            ),
            MagicMock(),
        )
        await service.process(
            _event(
                "message.failed",
                resource,
                contact_ids=["CT_delivery"],
                event_at=occurred_at + timedelta(minutes=1),
            ),
            MagicMock(),
        )
        await service.process(
            _event(
                "message.delivered",
                resource,
                contact_ids=["CT_delivery"],
                event_at=occurred_at + timedelta(minutes=3),
            ),
            MagicMock(),
        )
        await db.commit()

        assert (
            await db.execute(
                select(func.count(Message.id)).where(Message.provider_message_id == resource_id)
            )
        ).scalar_one() == 1
        message = (
            await db.execute(select(Message).where(Message.provider_message_id == resource_id))
        ).scalar_one()
        assert message.status == MessageStatus.DELIVERED
        assert message.delivered_at == occurred_at + timedelta(minutes=2)
        assert message.error_code is None
        assert message.error_message is None

        await db.delete(workspace)
        await db.commit()


@pytest.mark.parametrize("event_type", ["message.failed", "message.undelivered"])
async def test_failure_events_map_to_terminal_failure(event_type: str) -> None:
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, f"Quo {event_type}")
        resource_id = f"AC_failure_{uuid.uuid4().hex}"

        await _service(db, workspace.id).process(
            _event(
                event_type,
                _message_resource(
                    resource_id,
                    direction="outgoing",
                    created_at=occurred_at,
                ),
                event_at=occurred_at + timedelta(minutes=1),
            ),
            MagicMock(),
        )
        await db.commit()

        message = (
            await db.execute(select(Message).where(Message.provider_message_id == resource_id))
        ).scalar_one()
        assert message.status == MessageStatus.FAILED
        assert message.error_code == event_type.removeprefix("message.")

        await db.delete(workspace)
        await db.commit()


async def test_out_of_order_messages_keep_latest_preview_and_recompute_sla() -> None:
    inbound_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    outbound_at = inbound_at + timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo message ordering")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Ordering",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_ordering",
        )
        db.add(contact)
        await db.flush()
        service = _service(db, workspace.id)

        await service.process(
            _event(
                "message.delivered",
                _message_resource(
                    f"AC_outbound_{uuid.uuid4().hex}",
                    direction="outgoing",
                    created_at=outbound_at,
                    text="Newest preview",
                ),
                contact_ids=["CT_ordering"],
                event_at=outbound_at + timedelta(seconds=1),
            ),
            MagicMock(),
        )
        await service.process(
            _event(
                "message.received",
                _message_resource(
                    f"AC_inbound_{uuid.uuid4().hex}",
                    direction="incoming",
                    created_at=inbound_at,
                    text="Older inbound",
                ),
                contact_ids=["CT_ordering"],
                event_at=inbound_at,
            ),
            MagicMock(),
        )
        await db.commit()

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        assert conversation.last_message_at == outbound_at
        assert conversation.last_message_preview == "Newest preview"
        assert conversation.last_message_direction == "outbound"
        assert conversation.unread_count == 1
        assert conversation.first_inbound_at == inbound_at
        assert conversation.first_response_at == outbound_at
        assert conversation.first_response_seconds == 300
        assert contact.last_engaged_at == outbound_at

        await db.delete(workspace)
        await db.commit()


async def test_inbound_stop_records_global_opt_out_without_opt_in_inference() -> None:
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo opt out")
        service = _service(db, workspace.id)
        stop = _message_resource(
            f"AC_stop_{uuid.uuid4().hex}",
            direction="incoming",
            created_at=occurred_at,
            text="STOP",
        )
        await service.process(_event("message.received", stop), MagicMock())

        start = _message_resource(
            f"AC_start_{uuid.uuid4().hex}",
            direction="incoming",
            created_at=occurred_at + timedelta(minutes=1),
            text="START",
        )
        await service.process(_event("message.received", start), MagicMock())
        await db.commit()

        contact = (
            await db.execute(select(Contact).where(Contact.workspace_id == workspace.id))
        ).scalar_one()
        opt_out = (
            await db.execute(select(GlobalOptOut).where(GlobalOptOut.workspace_id == workspace.id))
        ).scalar_one()
        assert contact.sms_consent_status == "opted_out"
        assert contact.sms_consent_source == "quo_webhook"
        assert opt_out.phone_hash == hash_phone(CONTACT_PHONE)
        assert opt_out.opt_out_keyword == "stop"

        await db.delete(workspace)
        await db.commit()


async def test_sync_never_matches_a_contact_from_another_workspace() -> None:
    occurred_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace_a = await _workspace(db, "Quo tenant A")
        workspace_b = Workspace(name="Quo tenant B", slug=f"quo-b-{uuid.uuid4().hex}")
        db.add(workspace_b)
        await db.flush()
        other_contact = Contact(
            workspace_id=workspace_b.id,
            first_name="Other tenant",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_shared",
        )
        db.add(other_contact)
        await db.flush()

        fetched: dict[str, object] = {
            "id": "CT_shared",
            "firstName": "Tenant A",
            "lastName": None,
            "company": None,
            "emails": [],
            "phoneNumbers": [CONTACT_PHONE],
        }
        await _service(db, workspace_a.id, fetched_contact=fetched).process(
            _event(
                "message.received",
                _message_resource(
                    f"AC_tenant_{uuid.uuid4().hex}",
                    direction="incoming",
                    created_at=occurred_at,
                ),
                contact_ids=["CT_shared"],
            ),
            MagicMock(),
        )
        await db.commit()

        contacts_a = (
            (await db.execute(select(Contact).where(Contact.workspace_id == workspace_a.id)))
            .scalars()
            .all()
        )
        conversation = (
            await db.execute(
                select(Conversation).where(Conversation.workspace_id == workspace_a.id)
            )
        ).scalar_one()
        assert len(contacts_a) == 1
        assert contacts_a[0].id != other_contact.id
        assert contacts_a[0].external_id == "CT_shared"
        assert conversation.contact_id == contacts_a[0].id
        assert other_contact.last_engaged_at is None

        await db.delete(workspace_a)
        await db.delete(workspace_b)
        await db.commit()


async def test_answered_call_enriches_out_of_order_without_retry_duplicates() -> None:
    call_at = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)
    summary_at = call_at + timedelta(minutes=5)
    call_id = f"AC_voice_{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo answered call")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Voice",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_voice",
        )
        db.add(contact)
        await db.flush()
        service = _service(db, workspace.id)

        summary_resource: dict[str, object] = {
            "id": f"SUM_{uuid.uuid4().hex}",
            "callId": call_id,
            "fromPhoneNumber": CONTACT_PHONE,
            "model": "quill",
            "summary": ["Customer requested a roof estimate."],
            "nextSteps": ["Send available appointment times."],
        }
        transcript_resource: dict[str, object] = {
            "id": f"TR_{uuid.uuid4().hex}",
            "callId": call_id,
            "createdAt": (call_at + timedelta(minutes=2)).isoformat(),
            "duration": 65,
            "dialogue": [
                {
                    "identifier": CONTACT_PHONE,
                    "content": "Could I get a roof estimate?",
                    "start": 0,
                    "end": 3.5,
                    "speakerType": "human",
                },
                {
                    "identifier": WORKSPACE_PHONE,
                    "content": "Absolutely.",
                    "start": 4,
                    "end": 5,
                    "speakerType": "human",
                },
            ],
        }
        completed_resource = _call_resource(call_id, created_at=call_at)

        for event_type, resource, event_at in (
            ("call.summary.completed", summary_resource, summary_at),
            ("call.transcript.completed", transcript_resource, summary_at),
            ("call.summary.completed", summary_resource, summary_at),
            ("call.transcript.completed", transcript_resource, summary_at),
            ("call.completed", completed_resource, call_at + timedelta(seconds=65)),
            ("call.completed", completed_resource, call_at + timedelta(seconds=65)),
        ):
            await service.process(
                _voice_event(event_type, resource, event_at=event_at),
                MagicMock(),
            )
        await db.commit()

        messages = (
            (
                await db.execute(
                    select(Message)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(messages) == 1
        message = messages[0]
        assert message.provider_message_id == call_id
        assert message.channel == "voice"
        assert message.direction == MessageDirection.INBOUND
        assert message.status == MessageStatus.COMPLETED
        assert message.created_at == call_at
        assert message.duration_seconds == 65
        assert message.is_voicemail is False
        assert message.external_url == "https://my.quo.com/inbox/calls/test"
        assert message.recording_url is None
        assert "Customer requested a roof estimate." in message.body
        transcript = json.loads(message.transcript or "")
        assert transcript[0]["content"] == "Could I get a roof estimate?"

        conversation = (
            await db.execute(select(Conversation).where(Conversation.workspace_id == workspace.id))
        ).scalar_one()
        assert conversation.last_message_at == summary_at
        assert contact.last_engaged_at == summary_at

        encrypted_body, encrypted_transcript = (
            await db.execute(
                text("SELECT body, transcript FROM messages WHERE id = :message_id"),
                {"message_id": message.id},
            )
        ).one()
        assert "roof estimate" not in str(encrypted_body).lower()
        assert "roof estimate" not in str(encrypted_transcript).lower()

        await db.delete(workspace)
        await db.commit()


async def test_missed_call_is_a_failed_voice_timeline_record() -> None:
    call_at = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
    call_id = f"AC_missed_{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo missed call")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Missed",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_voice",
        )
        db.add(contact)
        await db.flush()

        resource = _call_resource(call_id, created_at=call_at)
        resource.pop("duration")
        resource.pop("status")
        await _service(db, workspace.id).process(
            _voice_event("call.missed", resource, event_at=call_at),
            MagicMock(),
        )
        await db.commit()

        message = (
            await db.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Conversation.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert message.channel == "voice"
        assert message.status == MessageStatus.FAILED
        assert message.error_code == "missed"
        assert message.duration_seconds is None
        assert message.is_voicemail is False
        assert message.body == "Incoming call missed"

        await db.delete(workspace)
        await db.commit()


async def test_voicemail_enriches_the_call_without_recording_or_duplication() -> None:
    call_at = datetime(2026, 8, 26, 16, 0, tzinfo=UTC)
    call_id = f"AC_voicemail_{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo voicemail")
        contact = Contact(
            workspace_id=workspace.id,
            first_name="Voicemail",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_voice",
        )
        db.add(contact)
        await db.flush()
        service = _service(db, workspace.id)

        voicemail_resource: dict[str, object] = {
            "id": f"VM_{uuid.uuid4().hex}",
            "callId": call_id,
            "createdAt": call_at.isoformat(),
            "updatedAt": (call_at + timedelta(seconds=18)).isoformat(),
            "duration": 18,
            "direction": "incoming",
            "from": CONTACT_PHONE,
            "to": WORKSPACE_PHONE,
            "caption": "Please call me back about the gutters.",
            "recordingUrl": "https://recordings.example.test/must-not-be-used",
        }
        await service.process(
            _voice_event("call.voicemail.completed", voicemail_resource),
            MagicMock(),
        )
        await service.process(
            _voice_event("call.voicemail.completed", voicemail_resource),
            MagicMock(),
        )

        missed_resource = _call_resource(call_id, created_at=call_at)
        missed_resource.pop("duration")
        missed_resource.pop("status")
        await service.process(
            _voice_event("call.missed", missed_resource),
            MagicMock(),
        )
        await db.commit()

        messages = (
            (
                await db.execute(
                    select(Message)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(Conversation.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(messages) == 1
        message = messages[0]
        assert message.provider_message_id == call_id
        assert message.status == MessageStatus.FAILED
        assert message.is_voicemail is True
        assert message.duration_seconds == 18
        assert message.transcript == "Please call me back about the gutters."
        assert message.body == "Incoming voicemail · 18s"
        assert message.recording_url is None

        await db.delete(workspace)
        await db.commit()


@pytest.mark.parametrize(
    ("event_type", "resource"),
    [
        (
            "call.completed",
            {
                "id": "AC_bad_duration",
                "direction": "incoming",
                "participants": [CONTACT_PHONE, WORKSPACE_PHONE],
                "status": "answered",
                "createdAt": "2026-08-26T17:00:00Z",
                "duration": -1,
            },
        ),
        (
            "call.transcript.completed",
            {
                "id": "TR_bad_dialogue",
                "callId": "AC_bad_dialogue",
                "createdAt": "2026-08-26T17:00:00Z",
                "duration": 5,
                "dialogue": "not-an-array",
            },
        ),
        (
            "call.summary.completed",
            {
                "id": "SUM_bad_summary",
                "callId": "AC_bad_summary",
                "summary": "not-an-array",
                "nextSteps": [],
            },
        ),
    ],
)
async def test_malformed_voice_data_is_rejected_before_creating_rows(
    event_type: str,
    resource: dict[str, object],
) -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Quo malformed call")

        with pytest.raises(QuoSyncError):
            await _service(db, workspace.id).process(
                _voice_event(event_type, resource),
                MagicMock(),
            )

        contact_count = await db.scalar(
            select(func.count()).select_from(Contact).where(Contact.workspace_id == workspace.id)
        )
        conversation_count = await db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.workspace_id == workspace.id)
        )
        assert contact_count == 0
        assert conversation_count == 0

        await db.delete(workspace)
        await db.commit()


async def test_voice_resolver_never_crosses_workspace_boundaries() -> None:
    call_at = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        workspace_a = await _workspace(db, "Quo voice tenant A")
        workspace_b = await _workspace(db, "Quo voice tenant B")
        contact_a = Contact(
            workspace_id=workspace_a.id,
            first_name="Tenant A",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_voice",
        )
        contact_b = Contact(
            workspace_id=workspace_b.id,
            first_name="Tenant B",
            phone_number=CONTACT_PHONE,
            external_source="quo",
            external_id="CT_voice",
        )
        db.add_all([contact_a, contact_b])
        await db.flush()

        await _service(db, workspace_a.id).process(
            _voice_event(
                "call.completed",
                _call_resource(
                    f"AC_isolated_{uuid.uuid4().hex}",
                    created_at=call_at,
                ),
                event_at=call_at + timedelta(seconds=65),
            ),
            MagicMock(),
        )
        await db.commit()

        conversation = (
            await db.execute(
                select(Conversation).where(Conversation.workspace_id == workspace_a.id)
            )
        ).scalar_one()
        workspace_b_message_count = await db.scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.workspace_id == workspace_b.id)
        )
        assert conversation.contact_id == contact_a.id
        assert workspace_b_message_count == 0
        assert contact_a.last_engaged_at == call_at
        assert contact_b.last_engaged_at is None

        await db.delete(workspace_a)
        await db.delete(workspace_b)
        await db.commit()
