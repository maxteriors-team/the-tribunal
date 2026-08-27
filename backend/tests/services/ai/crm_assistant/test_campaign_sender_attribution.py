"""CRM-assistant SMS tools attribute only workspace members."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.crm_assistant._campaign_tools import CampaignAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext


@pytest.mark.asyncio
async def test_send_sms_snapshots_context_user_with_workspace_membership() -> None:
    workspace_id = uuid.uuid4()
    contact = SimpleNamespace(
        id=91,
        first_name="Taylor",
        phone_number="+15555550100",
    )
    phone = SimpleNamespace(id=uuid.uuid4(), phone_number="+15555550101")
    sender = SimpleNamespace(
        id=73,
        full_name="Morgan Operator",
        email="morgan@example.com",
    )
    db = MagicMock()

    async def execute(statement: object) -> MagicMock:
        sql = str(statement)
        result = MagicMock()
        if "phone_numbers" in sql:
            result.scalar_one_or_none.return_value = phone
        elif "workspace_memberships" in sql:
            result.scalar_one_or_none.return_value = sender
        else:
            raise AssertionError(f"Unexpected query: {sql}")
        return result

    db.execute = AsyncMock(side_effect=execute)
    provider = MagicMock()
    provider.send_message = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    provider.close = AsyncMock()
    tools = CampaignAssistantTools(
        CRMToolContext(
            db=db,
            workspace_id=workspace_id,
            user_id=sender.id,
        )
    )

    with (
        patch(
            "app.services.ai.crm_assistant._campaign_tools.get_workspace_owned",
            AsyncMock(return_value=contact),
        ),
        patch(
            "app.services.telephony.text_provider.get_text_message_provider",
            return_value=provider,
        ),
    ):
        result = await tools.send_sms({"contact_id": contact.id, "body": "Hello"})

    assert result["success"] is True
    assert provider.send_message.await_args.kwargs["sender_user_id"] == sender.id
    assert provider.send_message.await_args.kwargs["sender_display_name"] == sender.full_name
