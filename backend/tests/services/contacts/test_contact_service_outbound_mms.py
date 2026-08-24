"""Contact-service orchestration tests for outbound MMS images."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.contacts import contact_service as contact_service_module
from app.services.contacts.contact_service import ContactService
from app.services.contacts.exceptions import ContactValidationError
from app.services.messaging.outbound_media import OutboundMedia


async def test_send_message_stores_image_and_forwards_media_to_telnyx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    contact = MagicMock(phone_number="+14155552671")
    workspace_phone = MagicMock(
        phone_number="+12125550101",
        imessage_enabled=False,
        mms_enabled=True,
        supports_mms=True,
        mac_relay_service=None,
    )
    workspace_phone.id = uuid.uuid4()
    media = OutboundMedia(
        attachment_id=uuid.uuid4(),
        provider_url="https://storage.example/signed-photo",
        storage_key=f"workspaces/{workspace_id}/outbound-attachments/photo.jpg",
        content_type="image/jpeg",
        size_bytes=123,
        sha256="a" * 64,
        filename="photo.jpg",
    )
    provider = MagicMock()
    provider.send_message = AsyncMock(return_value=MagicMock())
    provider.close = AsyncMock()
    store = AsyncMock(return_value=media)

    monkeypatch.setattr(
        contact_service_module,
        "get_text_message_provider",
        lambda *args, **kwargs: provider,
    )
    monkeypatch.setattr(contact_service_module, "store_outbound_image", store)

    service = ContactService(MagicMock())
    service.get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]
    service._get_workspace_phone = AsyncMock(return_value=workspace_phone)  # type: ignore[method-assign]

    await service.send_message(
        contact_id=7,
        workspace_id=workspace_id,
        message_body="Caption",
        image_data_url="data:image/jpeg;base64,placeholder",
    )

    store.assert_awaited_once_with(
        workspace_id=workspace_id,
        data_url="data:image/jpeg;base64,placeholder",
    )
    assert provider.send_message.await_args.kwargs["media"] == (media,)
    provider.close.assert_awaited_once()


async def test_send_message_rejects_image_when_selected_number_lacks_mms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    contact = MagicMock(phone_number="+14155552671")
    workspace_phone = MagicMock(
        phone_number="+12125550101",
        imessage_enabled=False,
        mms_enabled=False,
        supports_mms=False,
        mac_relay_service=None,
    )
    workspace_phone.id = uuid.uuid4()
    provider = MagicMock()
    provider.send_message = AsyncMock()
    provider.close = AsyncMock()
    store = AsyncMock()

    monkeypatch.setattr(
        contact_service_module,
        "get_text_message_provider",
        lambda *args, **kwargs: provider,
    )
    monkeypatch.setattr(contact_service_module, "store_outbound_image", store)

    service = ContactService(MagicMock())
    service.get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]
    service._get_workspace_phone = AsyncMock(return_value=workspace_phone)  # type: ignore[method-assign]

    with pytest.raises(ContactValidationError, match="does not support MMS"):
        await service.send_message(
            contact_id=7,
            workspace_id=workspace_id,
            message_body="",
            image_data_url="data:image/jpeg;base64,placeholder",
        )

    store.assert_not_awaited()
    provider.send_message.assert_not_awaited()
    provider.close.assert_awaited_once()
