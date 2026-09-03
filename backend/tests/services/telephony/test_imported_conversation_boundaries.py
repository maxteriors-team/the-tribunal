"""Native messaging lookups never reuse imported-provider conversations."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import Conversation
from app.services.contacts.ai_state_service import ContactAIStateService
from app.services.telephony.mac_relay import MacRelayMessageService
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.telnyx_voice import TelnyxVoiceService


def _db_returning(conversation: MagicMock) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = conversation
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _assert_native_only(statement: object) -> None:
    assert "conversations.source_provider IS NULL" in str(statement)


@pytest.mark.parametrize(
    "service",
    [
        TelnyxSMSService(api_key="test-key"),
        MacRelayMessageService(
            base_url="https://relay.example",
            token="test-token",
        ),
    ],
    ids=["telnyx", "mac-relay"],
)
async def test_native_text_lookup_excludes_imported_conversations(
    service: TelnyxSMSService,
) -> None:
    conversation = MagicMock(
        spec=Conversation,
        contact_id=42,
        assigned_agent_id=uuid.uuid4(),
    )
    db = _db_returning(conversation)

    found = await service._get_or_create_conversation(
        db,
        workspace_phone="+14155550199",
        contact_phone="+14155552671",
        workspace_id=uuid.uuid4(),
    )

    assert found is conversation
    _assert_native_only(db.execute.await_args.args[0])


async def test_native_voice_lookup_excludes_imported_conversations() -> None:
    conversation = MagicMock(spec=Conversation)
    db = _db_returning(conversation)

    found = await TelnyxVoiceService(api_key="test-key")._get_or_create_conversation(
        db,
        workspace_phone="+14155550199",
        contact_phone="+14155552671",
        workspace_id=uuid.uuid4(),
    )

    assert found is conversation
    _assert_native_only(db.execute.await_args.args[0])


async def test_contact_state_lookup_excludes_imported_conversations() -> None:
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    found = await ContactAIStateService(db)._find_contact_conversation(
        contact_id=42,
        workspace_id=uuid.uuid4(),
        contact_phone="(415) 555-2671",
        normalized_contact_phone="+14155552671",
    )

    assert found is None
    assert db.execute.await_count == 2
    for call in db.execute.await_args_list:
        _assert_native_only(call.args[0])
