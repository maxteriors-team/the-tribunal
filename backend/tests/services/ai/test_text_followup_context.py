"""Follow-up generation keeps durable context but cannot make unverified claims."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.message_context_builder import ContactGenerationContext
from app.services.ai.text_response_generator import generate_followup_message


@pytest.mark.asyncio
async def test_followup_blocks_mutable_claim_without_fresh_tools() -> None:
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=42,
        last_message_at=None,
        followup_count_sent=1,
    )
    contact = SimpleNamespace(
        first_name="Morgan",
        sms_consent_status="opted_in",
    )
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = contact
    db = AsyncMock()
    db.execute.return_value = query_result

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="Your quote is approved at $450."))
        ]
    )
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)

    with (
        patch(
            "app.services.ai.text_response_generator.build_message_context",
            AsyncMock(return_value=[{"role": "user", "content": "Checking in"}]),
        ),
        patch(
            "app.services.ai.text_response_generator.build_contact_generation_context",
            AsyncMock(
                return_value=ContactGenerationContext(
                    "<LIVE_CRM>quote=approved</LIVE_CRM>",
                    "Checking in",
                )
            ),
        ),
        patch(
            "app.services.ai.text_response_generator.AsyncOpenAI",
            return_value=client,
        ),
    ):
        response = await generate_followup_message(
            conversation,
            db,
            openai_api_key="test-key",
        )

    assert response == "Hi Morgan, just checking in - is there anything you'd like help with?"
    system_prompt = client.chat.completions.create.await_args.kwargs["messages"][0]["content"]
    assert "<LIVE_CRM>quote=approved</LIVE_CRM>" in system_prompt
    assert "No live tools are available" in system_prompt
    contact_query = str(db.execute.await_args.args[0])
    assert "contacts.workspace_id" in contact_query
