"""Outbound Messenger sending and the 24h window guard."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.conversation import Conversation, MessageChannel
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsValidationError,
    MetaMessagingWindowClosedError,
)
from app.services.telephony.messenger import MessengerMessageService
from app.services.telephony.text_provider import (
    UnreachableConversationError,
    get_text_message_provider,
    outbound_addresses,
    provider_for_conversation,
)


def _conversation(**overrides) -> Conversation:
    defaults = {
        "workspace_id": uuid.uuid4(),
        "channel": MessageChannel.MESSENGER,
        "messenger_psid": "1234567890123456",
    }
    return Conversation(**{**defaults, **overrides})


# --- routing -----------------------------------------------------------------


@pytest.mark.parametrize("channel", [MessageChannel.MESSENGER, MessageChannel.INSTAGRAM])
def test_dm_threads_route_to_the_messenger_provider(channel: MessageChannel) -> None:
    conversation = _conversation(channel=channel)
    assert provider_for_conversation(conversation) == channel.value
    provider = get_text_message_provider(channel.value)
    assert isinstance(provider, MessengerMessageService)


def test_sms_threads_still_route_to_telnyx() -> None:
    conversation = _conversation(
        channel=MessageChannel.SMS,
        messenger_psid=None,
        contact_phone="+14155550132",
        workspace_phone="+14155550100",
    )
    assert provider_for_conversation(conversation) is None


# --- addressing --------------------------------------------------------------


def test_a_dm_thread_is_addressed_by_page_scoped_id() -> None:
    to_address, from_address = outbound_addresses(_conversation())
    assert to_address == "1234567890123456"
    # The sending Page comes from the workspace integration at send time.
    assert from_address == ""


def test_a_phone_thread_is_addressed_by_its_phone_pair() -> None:
    conversation = _conversation(
        channel=MessageChannel.SMS,
        messenger_psid=None,
        contact_phone="+14155550132",
        workspace_phone="+14155550100",
    )
    assert outbound_addresses(conversation) == ("+14155550132", "+14155550100")


def test_a_thread_with_no_address_fails_loudly() -> None:
    """Better here than as an opaque provider error three layers down."""
    with pytest.raises(UnreachableConversationError):
        outbound_addresses(_conversation(messenger_psid=None))
    with pytest.raises(UnreachableConversationError):
        outbound_addresses(_conversation(channel=MessageChannel.SMS, messenger_psid=None))


# --- send guards -------------------------------------------------------------


def test_recipient_must_look_like_a_page_scoped_id() -> None:
    service = MessengerMessageService()
    assert service._normalize_outbound_to(" 1234567890123456 ") == "1234567890123456"
    for bad in ("+14155550132", "", "not-an-id", "1" * 65):
        with pytest.raises(MetaLeadAdsValidationError):
            service._normalize_outbound_to(bad)


def test_sending_without_resolved_credentials_refuses_rather_than_guesses() -> None:
    service = MessengerMessageService()
    with pytest.raises(MetaLeadAdsValidationError):
        service._normalize_outbound_from("anything")


def test_attachments_are_refused() -> None:
    service = MessengerMessageService()
    with pytest.raises(MetaLeadAdsValidationError):
        service._build_message_payload(
            to_number="1234567890123456",
            from_number="page-1",
            body="hi",
            idempotency_key=uuid.uuid4(),
            media_urls=["https://example.test/a.jpg"],
        )


# --- window ------------------------------------------------------------------


@pytest.mark.integration
async def test_a_closed_window_is_refused_before_any_graph_call() -> None:
    """Error 10 is not retryable, so the send must never leave the process."""
    from app.db.session import AsyncSessionLocal, engine
    from app.models.workspace import Workspace

    await engine.dispose()
    try:
        async with AsyncSessionLocal() as db:
            workspace = Workspace(
                id=uuid.uuid4(),
                name="Window Test",
                slug=f"win-{uuid.uuid4().hex[:8]}",
            )
            db.add(workspace)
            await db.flush()
            psid = str(uuid.uuid4().int % 10**16)
            db.add(
                Conversation(
                    workspace_id=workspace.id,
                    channel=MessageChannel.MESSENGER,
                    messenger_psid=psid,
                    messenger_window_expires_at=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
            await db.flush()

            service = MessengerMessageService()
            with pytest.raises(MetaMessagingWindowClosedError):
                await service._reject_if_window_closed(
                    db, workspace_id=workspace.id, psid=psid
                )
            await db.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_an_open_window_permits_the_send() -> None:
    from app.db.session import AsyncSessionLocal, engine
    from app.models.workspace import Workspace

    await engine.dispose()
    try:
        async with AsyncSessionLocal() as db:
            workspace = Workspace(
                id=uuid.uuid4(),
                name="Window Test",
                slug=f"win-{uuid.uuid4().hex[:8]}",
            )
            db.add(workspace)
            await db.flush()
            psid = str(uuid.uuid4().int % 10**16)
            db.add(
                Conversation(
                    workspace_id=workspace.id,
                    channel=MessageChannel.MESSENGER,
                    messenger_psid=psid,
                    messenger_window_expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            await db.flush()

            service = MessengerMessageService()
            await service._reject_if_window_closed(db, workspace_id=workspace.id, psid=psid)
            await db.rollback()
    finally:
        await engine.dispose()
